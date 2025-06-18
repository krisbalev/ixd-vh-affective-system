import json
import threading
from confluent_kafka import Consumer, Producer, KafkaError
import numpy as np
import config
import simulation
from processing import classifier
from utils import calculate_emotion_intensity
from optimizer import phi
from api_client import fetch_topic_schema
from fastavro.validation import validate
from fastavro import parse_schema

# Topics and configs
INPUT_TOPIC  = 'mood_input_topic'
OUTPUT_TOPIC = 'mood_output_topic'

brokers = "192.168.120.35:19003,192.168.120.35:19004,192.168.120.35:19005"

try:
    raw_in  = fetch_topic_schema(INPUT_TOPIC)
    raw_out = fetch_topic_schema(OUTPUT_TOPIC)
    avro_schema   = parse_schema(raw_in)
    avro_schema_out = parse_schema(raw_out)
except Exception as e:
    print(f"❌ Failed to load Avro schemas: {e}")
    raise

# 1) Initialize Consumer
consumer = Consumer({
    'bootstrap.servers': brokers ,
    'group.id': 'mood-group',
    'auto.offset.reset': 'latest',
    'enable.auto.commit': False
})
consumer.subscribe([INPUT_TOPIC])  

# 2) Initialize Producer
producer = Producer({
    'bootstrap.servers': brokers ,
    'linger.ms': 5,
    'batch.num.messages': 1000
})

def delivery_report(err, msg):
    """Called once for each produced message to indicate delivery result."""
    if err is not None:
        print(f"Delivery failed for record {msg.key()}: {err}")
    else:
        print(f"Message delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")

def forward_messages():
    """Continuously poll from INPUT_TOPIC and produce to OUTPUT_TOPIC."""
    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue  # no message, keep polling
            if msg.error():
                # Handle errors (e.g., rebalances or broker issues)
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"Consumer error: {msg.error()}")
                continue

            # 1) Parse incoming OCEAN + text
            payload     = json.loads(msg.value().decode('utf-8'))

            # Validate the schema
            if not validate(payload, avro_schema):
                print(f"⚠️  Invalid payload for schema {avro_schema['name']!r}: {payload!r}")
                consumer.commit(msg)
                continue

            user_text   = payload.get('user_message', '')
            ocean_vals  = payload.get('ocean_values', {})

            # 2) Recompute F and P
            F_new = np.array([
                ocean_vals.get('openness', 0.5),
                ocean_vals.get('conscientiousness', 0.5),
                ocean_vals.get('extraversion', 0.5),
                ocean_vals.get('agreeableness', 0.5),
                ocean_vals.get('neuroticism', 0.5),
            ])
            config.F = F_new
            config.P = config.Q @ config.F

            # 3) Reset simulation mood to the new personality
            with simulation.sim_lock:
                simulation.global_M = config.P.copy()
                simulation.mood_history.clear()

            # 4) Classify the user text
            try:
                results   = classifier(user_text)
                # adjust if pipeline returns nested list
                if isinstance(results, list) and isinstance(results[0], list):
                    results = results[0]
                best      = max(results, key=lambda x: x['score'])
                pred_label= best['label']
            except:
                pred_label = None

            # 5) Compute current simulation‐based emotion
            with simulation.sim_lock:
                sims = [
                    1 - np.dot(simulation.global_M, d) /
                        (np.linalg.norm(simulation.global_M)*np.linalg.norm(d) + 1e-9)
                    for d in config.D
                ]
                idx_sim = int(np.argmax(sims))

            # 6) If classifier matched, apply the emotion event
            mapped = None
            if pred_label:
                for lab in config.emotion_labels:
                    if lab.lower() == pred_label.lower():
                        mapped = lab; break
            if mapped:
                i      = config.emotion_labels.index(mapped)
                occ_int= np.random.rand()
                I      = calculate_emotion_intensity(
                            occ_int,
                            simulation.global_M,
                            config.P,
                            config.D[i],
                            config.TARGET_SHIFT
                         )
                with simulation.sim_lock:
                    simulation.global_M += config.alpha * phi[i] * I * config.D[i] * config.dt
                    simulation.mood_history.append((None, simulation.global_M.copy()))

            # 7) Determine the final current mood label
            with simulation.sim_lock:
                sims2 = [
                    1 - np.dot(simulation.global_M, d) /
                        (np.linalg.norm(simulation.global_M)*np.linalg.norm(d) + 1e-9)
                    for d in config.D
                ]
                current_mood = config.emotion_labels[int(np.argmax(sims2))]

            # 8) Produce only {"current_mood": "..."} downstream
            out_payload = {'current_mood': current_mood}
            # Validate the output against its Avro schema
            if not validate(out_payload, avro_schema_out):
                print(f"⚠️  Invalid output for schema {avro_schema_out['name']!r}: {out_payload!r}")
                # skip sending but still commit so we don't retry bad data
                consumer.commit(msg)
                continue

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
        # Clean up on exit
        consumer.close()
        producer.flush()
