import json
import threading
from confluent_kafka import Consumer, Producer, KafkaError
import numpy as np
import config
import simulation
from processing import classifier
from utils import calculate_emotion_intensity
from optimizer import phi
from api_client import fetch_topic_info
from fastavro.validation import validate
from fastavro import parse_schema

# Topics
INIT_TOPIC   = 'bigfive-topic'
INPUT_TOPIC  = 'mood-input-topic-123'
OUTPUT_TOPIC = 'mood-output-topic-123'

# Fetch schemas and bootstrap servers for each topic
try:
    info_init = fetch_topic_info(INIT_TOPIC)
    info_in   = fetch_topic_info(INPUT_TOPIC)
    info_out  = fetch_topic_info(OUTPUT_TOPIC)

    avro_schema_init = parse_schema(info_init['schema'])
    avro_schema_in   = parse_schema(info_in['schema'])
    avro_schema_out  = parse_schema(info_out['schema'])

    brokers = info_init['bootstrapServers']
except Exception as e:
    print(f"❌ Failed to load Avro schemas: {e}")
    raise

# Initialize Consumer subscribing to both init and input topics
consumer = Consumer({
    'bootstrap.servers': brokers,
    'group.id': 'mood-group',
    'auto.offset.reset': 'latest',
    'enable.auto.commit': False
})
consumer.subscribe([INIT_TOPIC, INPUT_TOPIC])

# Initialize Producer
producer = Producer({
    'bootstrap.servers': brokers,
    'linger.ms': 5,
    'batch.num.messages': 1000
})

def delivery_report(err, msg):
    if err is not None:
        print(f"Delivery failed for record {msg.key()}: {err}")
    else:
        print(f"Message delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")

# Main loop: handle init messages separately
try:
    while True:
        msg = consumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                print(f"Consumer error: {msg.error()}")
            continue

        topic = msg.topic()
        payload = json.loads(msg.value().decode('utf-8'))

        #  -- INIT topic: override Big Five & reset simulation
        if topic == INIT_TOPIC:
            if not validate(payload, avro_schema_init):
                print(f"⚠️ Invalid init payload: {payload}")
            else:
                # match schema field 'ocean_scores'
                ocean_scores = payload.get('ocean_scores', {})
                F_new = np.array([
                    ocean_scores.get('openness', 0.5),
                    ocean_scores.get('conscientiousness', 0.5),
                    ocean_scores.get('extraversion', 0.5),
                    ocean_scores.get('agreeableness', 0.5),
                    ocean_scores.get('neuroticism', 0.5),
                ])
                config.F = F_new
                config.P = config.Q @ config.F

                with simulation.sim_lock:
                    simulation.global_M = config.P.copy()
                    simulation.mood_history.clear()

                print(f"✅ Big Five overridden: {config.F}")
            consumer.commit(msg)
            continue

        #  -- USER input topic: classify and forward mood
        if topic == INPUT_TOPIC:
            # Validate input
            if not validate(payload, avro_schema_in):
                print(f"⚠️ Invalid input payload: {payload}")
                consumer.commit(msg)
                continue

            user_text = payload.get('user_message', '')

            # Classify text
            try:
                results = classifier(user_text)
                if isinstance(results, list) and isinstance(results[0], list):
                    results = results[0]
                best = max(results, key=lambda x: x['score'])
                pred_label = best['label']
            except Exception:
                pred_label = None

            # Simulation-based emotion
            with simulation.sim_lock:
                sims = [
                    1 - np.dot(simulation.global_M, d) / (
                        np.linalg.norm(simulation.global_M) * np.linalg.norm(d) + 1e-9)
                    for d in config.D
                ]
                idx_sim = int(np.argmax(sims))

            # Apply event if label matches
            mapped = None
            if pred_label:
                for lab in config.emotion_labels:
                    if lab.lower() == pred_label.lower():
                        mapped = lab
                        break
            if mapped:
                i = config.emotion_labels.index(mapped)
                occ_int = np.random.rand()
                I = calculate_emotion_intensity(
                    occ_int,
                    simulation.global_M,
                    config.P,
                    config.D[i],
                    config.TARGET_SHIFT
                )
                with simulation.sim_lock:
                    simulation.global_M += config.alpha * phi[i] * I * config.D[i] * config.dt
                    simulation.mood_history.append((None, simulation.global_M.copy()))

            # Determine current mood
            with simulation.sim_lock:
                sims2 = [
                    1 - np.dot(simulation.global_M, d) / (
                        np.linalg.norm(simulation.global_M) * np.linalg.norm(d) + 1e-9)
                    for d in config.D
                ]
                current_mood = config.emotion_labels[int(np.argmax(sims2))]

            # Produce output including original message
            out_payload = {
                'user_message': user_text,
                'current_mood': current_mood
            }
            if not validate(out_payload, avro_schema_out):
                print(f"⚠️ Invalid output payload: {out_payload}")
            else:
                producer.produce(
                    OUTPUT_TOPIC,
                    key=None,
                    value=json.dumps(out_payload).encode('utf-8'),
                    callback=delivery_report
                )
                producer.poll(0)

            consumer.commit(msg)

except KeyboardInterrupt:
    pass
finally:
    consumer.close()
    producer.flush()