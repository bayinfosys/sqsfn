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
     + if on_invalid or on_fail have been called the message will not be removed from the queue
     + the validator should return a validated version of the message body or None.
       The return value is passed to the decorated function if not None.

     returns None
  """
  # validate the inputs
  assert sqs_queue_name is not None, "sqs_queue_name cannot be none"

  # apply the decorator
  def sqs_queue_listener_decorator(fn):
    async def wrapper(*args, **kwargs):
      sqs = boto3.client("sqs",
          aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", None),
          aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", None),
          endpoint_url=os.getenv("AWS_SQS_ENDPOINT") or None
      )

      try:
        sqs_queue_url = sqs.get_queue_url(QueueName=sqs_queue_name)["QueueUrl"]
      except sqs.exceptions.QueueDoesNotExist as e:
        logger.warning("'%s' does not exist" % sqs_queue_name)
        return None

      # receive message from SQS queue
      response = sqs.receive_message(
          QueueUrl=sqs_queue_url,
          AttributeNames=["SentTimestamp"],
          MaxNumberOfMessages=max_messages,
          MessageAttributeNames=["All"],
          VisibilityTimeout=visibility_timeout,
          WaitTimeSeconds=wait_time
      )

      messages = response.get("Messages", [])

      if len(messages) == 0:
        return None

      logger.debug("processing %i messages with '%s'", len(messages), str(fn.__name__))

      for message in messages:
        body = json.loads(message["Body"])
        receipt_handle = message["ReceiptHandle"]

        logger.debug("'%s': '%s'", message["MessageId"], str(body))

        # validate the message object
        if validator is not None:
          body = validator(body)
          if body is None:
            if on_invalid:
              on_invalid(body)
            continue

        # process the message
        try:
          if asyncio.iscoroutine(fn):
            retval = await fn(body, *args, **kwargs)
          else:
            retval = fn(body, *args, **kwargs)
        except Exception as e:
          logger.exception("error processing '%s' on '%s'", str(body), str(sqs_queue_name))
          # delete the message or add to dead letter?
          retval = False

        # delete received message from queue if the handler returned True
        if retval is True:
          logger.debug("delete '%s'", message["MessageId"])
          sqs.delete_message(
              QueueUrl=sqs_queue_url,
              ReceiptHandle=receipt_handle
          )

          if on_success is not None:
            on_success(body)
        else:
          logger.debug("'%s' processing returned false", receipt_handle)

          if on_fail is not None:
            on_fail(body)

    # add the wrapper to the queue_listeners set
    logger.debug("adding '%s'[%s] to QUEUE_LISTENERS", str(wrapper.__name__), str(fn.__name__))
    QUEUE_LISTENERS[sqs_queue_name] = wrapper
    return wrapper

  return sqs_queue_listener_decorator


def post(sqs_queue_name: str, data: dict):
  """utility function to post an object to an SQS endpoint
  """
  sqs = boto3.client("sqs",
      aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", None),
      aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", None),
      endpoint_url=os.getenv("AWS_SQS_ENDPOINT", None)
  )

  queue_url = sqs.get_queue_url(QueueName=sqs_queue_name)["QueueUrl"]

  resp = sqs.send_message(
      QueueUrl=queue_url,
      MessageBody=json.dumps(data)
  )

  logger.info("%s.response: [%s] %s", sqs_queue_name, str(resp["ResponseMetadata"]["HTTPStatusCode"]), str(resp["MessageId"]))
  logger.debug("%s.response: '%s' for '%s'", sqs_queue_name, str(resp), str(queue_url))

  return resp["MessageId"]


async def listen(poll_interval: int = 5):
  """entrypoint for processing queue items

     poll_interval: delay in seconds between each iteration of the listen loop

     NB: poll_interval is added to the sum of all wait_time decorator parameters
  """
  logger.info("listening for '%s'", str(QUEUE_LISTENERS.keys()))

  while True:
    for k, v in QUEUE_LISTENERS.items():
      try:
        retval = await v()
      except KeyboardInterrupt as e:
        logger.error("KeyboardInterrupt")
        return
      except Exception as e:
        # FIXME: add a retry limit, if > retry limit delete this kv
        logger.exception("error processing '%s'", k)
        continue

    await asyncio.sleep(poll_interval)
