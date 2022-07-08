"""utility functions for sqs service
"""
import os
import logging
import inspect
import boto3
import botocore
import json
import asyncio


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "WARNING"))


QUEUE_LISTENERS = {}


def __get_client():
  sqs = boto3.client("sqs",
      aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", None),
      aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", None),
      endpoint_url=os.getenv("AWS_SQS_ENDPOINT") or None
  )

  return sqs


def __get_queue_url(sqs, sqs_queue_name: str):
  try:
    return sqs.get_queue_url(QueueName=sqs_queue_name)["QueueUrl"]
  except sqs.exceptions.QueueDoesNotExist as e:
    logger.warning("'%s' does not exist" % sqs_queue_name)
    return None
  except botocore.exceptions.EndpointConnectionError as e:
    logger.error(str(e))
    return None


def __get_messages(
      sqs,
      sqs_queue_url: str,
      max_messages: int=1,
      visibility_timeout: int=2,
      wait_time: int=1
  ) -> list:
  """helper function to get messages on the queue.
     returns a list of messages or empty list (if no messages) or None (if no queue)
  """
  # receive message from SQS queue
  try:
    response = sqs.receive_message(
        QueueUrl=sqs_queue_url,
        AttributeNames=["SentTimestamp"],
        MaxNumberOfMessages=max_messages,
        MessageAttributeNames=["All"],
        VisibilityTimeout=visibility_timeout,
        WaitTimeSeconds=wait_time
    )
  except botocore.exceptions.ParamValidationError as e:
    logger.error(str(e))
    return []

  return response.get("Messages") or []


def sqs_queue_listener(
    sqs_queue_name: str,
    wait_time: int=20,
    max_messages: int=10,
    visibility_timeout: int=10,
    validator=None,
    on_invalid=None,
    on_success=None,
    on_fail=None
  ):
  """decorator to wrap around functions which process queue data

     on error (QueueDoesNotExist, empty queue, etc) no processing is performed

     if the decorated functionevaluates to True, the message is deleted from the
     queue, otherwise, the message remains on the queue.

     sqs_queue_name: name of the queue to poll
     wait_time: time in seconds to wait for new message
     max_messages: maximum number of messages to pull from the queue
     visibility_timeout: time in seconds to block read messages from other queue readers
     validator: optional function which validates the message body, returns None on invalid message
     on_invalid: optional function to call when the validator fails
     on_success: optional function to call when the message is successfully processed
     on_fail: optional function to call when the message is not successfully processed

     Notes:
     + the async-ness of fn and validator must match (i.e., if fn is async, validator must be async)
     + on_invalid, on_success and on_fail are never required to be async so can be lambda definitions
     + if on_invalid or on_fail have been called the message will not be removed from the queue
     + the validator should return a validated version of the message body or None.
     + the return value of validator is passed to the decorated function if not None.
     + if the validator returns None, the body of the message is considered invalid and on_invalid is called

     returns None
  """
  # validate the inputs
  assert sqs_queue_name is not None, "sqs_queue_name cannot be none"

  # set default functions so we don't mess about with if none
  default_on_fail = lambda x: True
  default_on_success = lambda x: True

  on_fail = on_fail or default_on_fail
  on_success = on_success or default_on_success

  # apply the decorator
  def sqs_queue_listener_decorator(fn):
    if inspect.iscoroutinefunction(fn):
      # parallel message processing
      async def wrapper(*args, **kwargs):
        sqs = __get_client()
        url = __get_queue_url(sqs, sqs_queue_name)

        if url is None:
          logger.warning("'%s' unable to fetch url", sqs_queue_name)
          return None

        messages = __get_messages(sqs, url, max_messages=max_messages, wait_time=wait_time, visibility_timeout=visibility_timeout)

        if len(messages) == 0:
          return None

        # load the messages
        receipts = {m["MessageId"]: m["ReceiptHandle"] for m in messages}
        msg_body = {m["MessageId"]: json.loads(m["Body"]) for m in messages}
        # validate the messages
        vms = {m: x for m, x in zip(msg_body, (validator(m) for m in msg_body.values())) if x is not None} if validator is not None else msg_body

        # gather the responses
        retvals = await asyncio.gather(*[fn(v, *args, **kwargs) for v in vms.values()], return_exceptions=True)

        # delete the processed messages
        for msg_id, retval in zip(vms, retvals):
          if retval:
            if isinstance(retval, Exception):
              logger.exception("'%s' on '%s' error with '%s'", str(fn.__name__), str(sqs_queue_name), str(msg_body[msg_id]))
              raise retval
              # delete the message or add to dead letter?
            else:
              sqs.delete_message(QueueUrl=url, ReceiptHandle=receipts[msg_id])
              on_success(msg_body[msg_id])
          else:
            logger.warning("'%s/%s' returned '%s' for '%s'", sqs_queue_name, msg_id, str(retval), msg_body[msg_id])
            on_fail(msg_body[msg_id])
    else:
      # serial message processing
      def wrapper(*args, **kwargs):
        sqs = __get_client()
        url = __get_queue_url(sqs, sqs_queue_name)
        messages = __get_messages(sqs, url, max_messages=max_messages, wait_time=wait_time, visibility_timeout=visibility_timeout)

        # serial message processing
        for message in messages:
          body = json.loads(message["Body"])
          receipt_handle = message["ReceiptHandle"]

          # validate the message object
          body = validator(body) if validator is not None else body

          if body is None:
            on_invalid(body)
            continue

          # process the message
          try:
            retval = fn(body, *args, **kwargs)
          except Exception as e:
            logger.exception("error processing '%s' on '%s'", str(body), str(sqs_queue_name))
            # FIXME: add to dead letter?
            retval = False
            raise e
          finally:
            # delete received message from queue if the handler returned True
            if retval:
              logger.debug("delete '%s'", message["MessageId"])
              sqs.delete_message(QueueUrl=url, ReceiptHandle=receipt_handle)
              on_success(body)
            else:
              logger.warning("'%s/%s' returned '%s' for '%s'", sqs_queue_name, message["MessageId"], str(retval), str(body))
              on_fail(body)

    # add the wrapper to the queue_listeners set
    logger.debug("listening to '%s' with '%s' to QUEUE_LISTENERS", sqs_queue_name, str(fn.__name__))

    # ensure all listeners are async or all are not async
    if inspect.iscoroutinefunction(wrapper) != all([inspect.iscoroutinefunction(v) for v in QUEUE_LISTENERS.values()]):
      logger.error("'%s' asyncness does not match existing queue listener asyncnesses", str(fn.__name__))
      raise NotImplementedError("cannot mix async and non-async queue listeners")

    QUEUE_LISTENERS[sqs_queue_name] = wrapper
    return wrapper

  return sqs_queue_listener_decorator


def post(sqs_queue_name: str, data: dict):
  """utility function to post an object to an SQS endpoint
  """
  sqs = __get_client()
  queue_url = __get_queue_url(sqs, sqs_queue_name)

  if queue_url is None:
    logger.warning("could not get url for '%s'", sqs_queue_name)
    return None

  try:
    resp = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(data)
    )
  except sqs.exceptions.InvalidMessageContents as e:
    logger.warning("'%s' invalid contents [%s]", sqs_queue_name, str(data))
    raise e

  return resp["MessageId"]


async def alisten(poll_interval: int = 5):
  """entrypoint for processing queue items

     poll_interval: delay in seconds between each iteration of the listen loop

     NB: poll_interval is added to the sum of all wait_time decorator parameters
  """
  logger.info("listening for '%s'", str(QUEUE_LISTENERS.keys()))

  while True:
    retvals = {k: r for k, r in zip(QUEUE_LISTENERS, await asyncio.gather(*[v() for v in QUEUE_LISTENERS.values()]))}
    await asyncio.sleep(poll_interval)


def listen(poll_interval: int = 5):
  """entrypoint for processing queue items non-asynchronsly
     fastapi (or starlette) background tasks will run this in a threadpool

     poll_interval: delay in seconds between each iteration of the listen loop

     NB: poll_interval is added to the sum of all wait_time decorator parameters
  """
  from time import sleep

  logger.info("listening for '%s'", str(QUEUE_LISTENERS.keys()))

  while True:
    for k, v in QUEUE_LISTENERS.items():
      try:
        retval = v()
      except KeyboardInterrupt as e:
        logger.error("KeyboardInterrupt")
        return
      except Exception as e:
        # FIXME: add a retry limit, if > retry limit delete this kv
        logger.exception("error processing '%s'", k)
        continue

    sleep(poll_interval)
