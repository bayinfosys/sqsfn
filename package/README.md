# SQS Callback decorator

Python decorator for registering message handlers from Simple Queue Service endpoints.


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
