import time
import threading
import numpy as np
from optimizer import phi
import time, threading, numpy as np
from sys_config import (
    P, dt, lambda_m, D, S, alpha,
    emotion_labels   # ← labels for the tag we’ll store
)
# –– InfluxDB ––––––––––––––––––––––––––––––––––––––––––
from decouple import config
from influxdb_client import InfluxDBClient, Point
from scipy.spatial.distance import cosine

# client is light‑weight; safe to have one per thread
influx_client = InfluxDBClient(
    url   = config("INFLUX_URL",  default="http://localhost:8086"),
    token = config("INFLUX_TOKEN",default="my-super-secret-token"),
    org   = config("INFLUX_ORG",  default="my-org"),
)
write_api = influx_client.write_api()

# Global variables for simulation
global_M = P.copy()  # starting mood at personality point
mood_history = []
start_time = time.time()
sim_lock = threading.Lock()
running_flag = None  # set by main
current_vh_id = None

# Mood update loop
def update_mood():
    global global_M
    while running_flag.value:
        with sim_lock:
            # Virtual event: randomly select an emotion index
            idx = np.random.choice(S)
            I = 0.01  # low intensity for background events
            d = D[idx]
            # Update mood: add event influence and apply decay
            global_M += alpha * phi[idx] * I * d * dt
            global_M *= np.exp(-lambda_m * dt)
            # Normalize if necessary
            if np.max(np.abs(global_M)) > 1.0:
                global_M = global_M / np.max(np.abs(global_M))
            # Save current time and mood
            mood_history.append((time.time() - start_time, global_M.copy()))
            if current_vh_id is not None:          # skip until first VH seen
                idx_sim = int(np.argmax([
                    1 - cosine(global_M, d) for d in D
                ]))
                label = emotion_labels[idx_sim]

            point = (
                Point("mood_updates")
                  .tag("vh_id", str(current_vh_id))
                  .tag("label",  label)
                  .field("Pleasure",   float(global_M[0]))
                  .field("Arousal",    float(global_M[1]))
                  .field("Dominance",  float(global_M[2]))
                  .time(int(time.time() * 1e9))  # ns
            )
            try:
                write_api.write(bucket=config("INFLUX_BUCKET"), record=point)
            except Exception as e:
                print(f"❌ InfluxDB write error (update_mood): {e}")

        time.sleep(dt)

    influx_client.close()  # graceful shutdown