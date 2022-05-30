# SQS Callback decorator

Python decorator for registering message handlers from Simple Queue Service endpoints.

+ decorator register callbacks for specific queues
+ `listen` to iterate over all callbacks, read messages from queues and dispatch
+ `post` to quickly send data to a queue and obtain message ID


## install

```bash
pip install bayis-sqs-callback
```

## usage

```python
import sqsfn

@sqsfn.sqs_queue_listener(sqs_queue_name="my-queue-name")
def my_example_queue_listener(data_from_queue):
  """process a queue item"""
  print("recieved data")
  return True


if __name__ == "__main__":
  asyncio.run(sqsfn.listen())
```


## multiple queues

```python
import sqsfn

@sqsfn.sqs_queue_listener(sqs_queue_name="queue-a")
def my_example_queue_listener(data_from_queue_a):
  print("received from queue a")
  sqsfn.post("queue-b", data_from_queue_a)
  return True

@sqsfn.sqs_queue_listener(sqs_queue_name="queue-b")
def my_example_queue_listener(data_from_queue_b):
  print("received from queue b")
  sqsfn.post("queue-c", data_from_queue_b)
  return True

@sqsfn.sqs_queue_listener(sqs_queue_name="queue-c")
def my_example_queue_listener(data_from_queue_c):
  print("received from queue c")
  sqsfn.post("queue-a", data_from_queue_c)
  return True

if __name__ == "__main__":
  asyncio.run(sqsfn.listen())
```

## success and failure queues

the `on_success` and `on_fail` optional parameters accept a function which
will be called on successful processing of the message or otherwise.

```python
import sqsfn

@sqsfn.sqs_queue_listener(
    sqs_queue_name="my-queue-name",
    on_success=lambda x: sqsfn.post("my-success-queue", x),
    on_fail=lambda x: sqsfn.post("my-fail-queue", x)
)
def my_example_queue_listener(data_from_queue):
  """process a queue item"""
  print("recieved data")
  return True


if __name__ == "__main__":
  asyncio.run(sqsfn.listen())
```
