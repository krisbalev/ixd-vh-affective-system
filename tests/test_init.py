# test_init.py
# Sends an init message with OCEAN scores to the init-bigfive-topic

import json
from confluent_kafka import Producer
import argparse

def main():
    parser = argparse.ArgumentParser(description="Publish a Big Five init message.")
    parser.add_argument('--vh_id', required=True, help='User/vehicle/session ID')
    parser.add_argument('--openness', type=float, default=0.5)
    parser.add_argument('--conscientiousness', type=float, default=0.5)
    parser.add_argument('--extraversion', type=float, default=0.5)
    parser.add_argument('--agreeableness', type=float, default=0.5)
    parser.add_argument('--neuroticism', type=float, default=0.5)
    parser.add_argument('--broker', default='192.168.120.200:9092', help='Kafka bootstrap server')
    args = parser.parse_args()

    payload = {
        'vh_id': args.vh_id,
        'ocean_scores': {
            'openness': args.openness,
            'conscientiousness': args.conscientiousness,
            'extraversion': args.extraversion,
            'agreeableness': args.agreeableness,
            'neuroticism': args.neuroticism,
        }
    }

    producer = Producer({'bootstrap.servers': args.broker})
    producer.produce('init-bigfive-topic', json.dumps(payload).encode('utf-8'))
    producer.flush()
    print(f"Sent init payload: {payload}")

if __name__ == '__main__':
    main()