import json, time, threading
from datetime import datetime
import numpy as np
from confluent_kafka import Consumer, Producer, KafkaError
from fastavro import parse_schema
from fastavro.validation import validate
from influxdb_client import InfluxDBClient, Point
from pymongo import MongoClient
import sys_config
import simulation
from api_client import fetch_topic_info
from optimizer import phi
from processing import classifier
from utils import calculate_emotion_intensity
from decouple import config

# ——————— InfluxDB client ————————
influx_client = InfluxDBClient(
    url=config('INFLUX_URL', default='http://localhost:8086'),
    token=config('INFLUX_TOKEN', default='my-super-secret-token'),
    org=config('INFLUX_ORG', default='my-org'),
)
write_api = influx_client.write_api()

# ——————— MongoDB client —————————
mongo_client = MongoClient(config('MONGO_URI', default='mongodb://localhost:27017'))
mongo_db     = mongo_client[config('MONGO_DB', default='mood_db')]
init_coll    = mongo_db[config('MONGO_COLL_INIT', default='ocean_scores')]

# Topics
INIT_TOPIC = 'bigfive-topic'
INPUT_TOPIC = config('INPUT_TOPIC')
OUTPUT_TOPIC = config('OUTPUT_TOPIC')

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
    'group.id': f"mood-group-{int(time.time())}",
    'auto.offset.reset': 'earliest',
    'enable.auto.commit': False
})

# subscribe to the fixed INIT topic plus all matching input topics
print("🛈 Subscribing to", [INIT_TOPIC, INPUT_TOPIC], "on", brokers)
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
def run_consumer_loop():
    try:
        active_vh = None
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                print(".", end="", flush=True)  
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"Consumer error: {msg.error()}")
                continue

            topic   = msg.topic()
            payload = json.loads(msg.value().decode('utf-8'))

            vh_id = payload.get("vh_id")

            # --- VH switch logic ---
            if vh_id != active_vh:
                # 1) load Big‑Five from MongoDB
                doc = init_coll.find_one({"vh_id": vh_id})
                if doc and "ocean_scores" in doc:
                    oscores = doc["ocean_scores"]
                    F_new = np.array([
                        oscores.get('openness', 0.5),
                        oscores.get('conscientiousness', 0.5),
                        oscores.get('extraversion', 0.5),
                        oscores.get('agreeableness', 0.5),
                        oscores.get('neuroticism', 0.5),
                    ])
                    sys_config.F = F_new
                    sys_config.P = sys_config.Q @ sys_config.F

                # 2) fetch latest PAD from InfluxDB
                query = f'''
                from(bucket: "{config('INFLUX_BUCKET')}")
                  |> range(start: -30d)
                  |> filter(fn: (r) =>
                       r._measurement == "mood_updates" and
                       r.vh_id == "{vh_id}"
                  )
                  |> last()
                '''
                tables = influx_client.query_api().query(org=config('INFLUX_ORG'), query=query)
                # extract the PAD fields (Pleasure, Arousal, Dominance)
                for table in tables:
                    for record in table.records:
                        # record._field is one of "Pleasure","Arousal","Dominance"
                        # accumulate into a dict
                        pass  # see below for full snippet

                # you might instead gather into a dict:
                pad_vals = {"Pleasure": None, "Arousal": None, "Dominance": None}
                for table in tables:
                    for rec in table.records:
                        pad_vals[rec.get_field()] = rec.get_value()
                if all(v is not None for v in pad_vals.values()):
                    with simulation.sim_lock:
                        simulation.global_M = np.array([
                            pad_vals["Pleasure"],
                            pad_vals["Arousal"],
                            pad_vals["Dominance"],
                        ])
                        simulation.mood_history[:] = []

                else:
                    with simulation.sim_lock:
                        simulation.global_M = sys_config.P.copy()
                        simulation.mood_history[:] = []


                active_vh = vh_id
                simulation.current_vh_id = vh_id
                print(f"🆕 Switched active VH to {vh_id}; loaded F={sys_config.F} and M={simulation.global_M}")

            #  -- INIT topic: override Big Five & reset simulation
            print(f"Topic: {topic}, vh_id: {vh_id}, payload: {payload}")
            print(f"{INIT_TOPIC} received for vh_id={vh_id}")
            if topic == INIT_TOPIC:
                if not validate(payload, avro_schema_init):
                    print(f"⚠️ Invalid init payload: {payload}")
                else:
                    print(f"🆕 Received init payload for vh_id={vh_id}: {payload}")
                    # match schema field 'ocean_scores'
                    ocean_scores = payload.get("ocean_scores", {})
                    try:
                        init_coll.update_one(
                            {"vh_id": vh_id},
                            {"$set": {
                                "ocean_scores": ocean_scores,
                                "last_update":  datetime.utcnow()
                            }},
                            upsert=True
                        )
                        print(f"✅ MongoDB: upserted ocean_scores for vh_id={vh_id}")
                    except Exception as e:
                        print(f"❌ MongoDB write error for vh_id={vh_id}:", e)                
                    F_new = np.array([
                        ocean_scores.get('openness', 0.5),
                        ocean_scores.get('conscientiousness', 0.5),
                        ocean_scores.get('extraversion', 0.5),
                        ocean_scores.get('agreeableness', 0.5),
                        ocean_scores.get('neuroticism', 0.5),
                    ])
                    sys_config.F = F_new
                    sys_config.P = sys_config.Q @ sys_config.F

                    with simulation.sim_lock:
                        simulation.global_M = sys_config.P.copy()
                        simulation.mood_history[:] = []
                        
                    print(f"✅ Big Five overridden: {sys_config.F}")
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
                        for d in sys_config.D
                    ]
                    idx_sim = int(np.argmax(sims))

                # Apply event if label matches
                mapped = None
                if pred_label:
                    for lab in sys_config.emotion_labels:
                        if lab.lower() == pred_label.lower():
                            mapped = lab
                            break
                if mapped:
                    i = sys_config.emotion_labels.index(mapped)
                    occ_int = np.random.rand()
                    I = calculate_emotion_intensity(
                        occ_int,
                        simulation.global_M,
                        sys_config.P,
                        sys_config.D[i],
                        sys_config.TARGET_SHIFT
                    )
                    with simulation.sim_lock:
                        simulation.global_M += sys_config.alpha * phi[i] * I * sys_config.D[i] * sys_config.dt
                        simulation.mood_history.append((None, simulation.global_M.copy()))

                # Determine current mood
                with simulation.sim_lock:
                    sims2 = [
                        1 - np.dot(simulation.global_M, d) / (
                            np.linalg.norm(simulation.global_M) * np.linalg.norm(d) + 1e-9)
                        for d in sys_config.D
                    ]
                    current_mood = sys_config.emotion_labels[int(np.argmax(sims2))]
                    pad          = simulation.global_M.copy()  # [P, A, D] floats

                    # timestamp in nanoseconds
                    ts = int(time.time() * 1e9)

                    point = (
                        Point("mood_updates")
                          .tag("vh_id", str(vh_id))
                          .tag("label", current_mood)
                          .field("Pleasure", float(pad[0]))
                          .field("Arousal", float(pad[1]))
                          .field("Dominance", float(pad[2]))
                          .time(ts)
                    )

                    try:
                        write_api.write(bucket=config('INFLUX_BUCKET'), record=point)
                        print(f"✅ InfluxDB: wrote mood {current_mood} for vh_id={vh_id}")
                    except Exception as e:
                        print(f"❌ InfluxDB write error for vh_id={vh_id}:", e)

                # Produce output including original message
                out_payload = {
                    'vh_id': vh_id,
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
        influx_client.close()
        mongo_client.close()

if __name__ == "__main__":
    run_consumer_loop()