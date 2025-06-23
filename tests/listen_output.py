import json
from confluent_kafka import Consumer, KafkaError

def main():
    brokers = '192.168.120.200:9092'
    topic = 'bigfive-topic'
    consumer = Consumer({
        'bootstrap.servers': brokers,
        'group.id': 'test-output-listener',
        'auto.offset.reset': 'latest'
    })
    consumer.subscribe([topic])

    print(f"Listening on {topic}... (Ctrl+C to exit)")
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"Consumer error: {msg.error()}")
                continue
            data = json.loads(msg.value().decode('utf-8'))
            print(f"Received: {data}")
    except KeyboardInterrupt:
        print("Exiting consumer.")
    finally:
        consumer.close()

if __name__ == '__main__':
    main()
