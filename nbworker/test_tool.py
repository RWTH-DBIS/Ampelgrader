"""
Very ugly script for regeression testing the worker
"""
import pika
import os
import sys
from nbblackbox_common import NBBBGradingRequest

RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "127.0.0.1")
RABBITMQ_QUEUE = os.environ.get("RABBITMQ_QUEUE", "grading")
RABBITMQ_RSP_QUEUE = os.environ.get("RABBITMQ_RSP_QUEUE", "grading_rsp")

con = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
channel = con.channel()
# setup queues to be durable, so they outlive container stop
channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
channel.queue_declare(queue=RABBITMQ_RSP_QUEUE, durable=True)

nb = None
with open("source/UB-1/UB-1.ipynb") as f:
    nb = f.read()

channel.basic_publish(exchange='', routing_key=RABBITMQ_QUEUE, body=NBBBGradingRequest(1, "UB-1", {"UB-1.ipynb": nb}).dump())

def callback(ch, method, properties, body):
        print(f" [x] Received {body}")

channel.basic_consume(queue=RABBITMQ_RSP_QUEUE, on_message_callback=callback, auto_ack=True)
try:
    channel.start_consuming()
except KeyboardInterrupt:
    print('Interrupted')
    try:
        sys.exit(0)
    except SystemExit:
        os._exit(0)