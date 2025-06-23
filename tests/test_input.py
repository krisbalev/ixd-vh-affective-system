import json
from confluent_kafka import Producer
import argparse

def main():
    parser = argparse.ArgumentParser(description="Publish a user input message.")
    parser.add_argument('--vh_id',   required=True, help='User/vehicle/session ID')
    parser.add_argument('--message', required=True, help='User message text')
    parser.add_argument('--broker', default='192.168.120.200:9092', help='Kafka bootstrap server')
    args = parser.parse_args()

    payload = {
    'vh_id':         args.vh_id,
    'user_message':  args.message
    }

    producer = Producer({'bootstrap.servers': args.broker})
    producer.produce('user-input-topic', json.dumps(payload).encode('utf-8'))
    producer.flush()
    print(f"Sent user input: {payload}")

if __name__ == '__main__':
    main()