import asyncio
from transformers import pipeline
import numpy as np
from scipy.spatial.distance import cosine

import simulation
from config import P, TARGET_SHIFT, D, emotion_labels, dt, alpha
from optimizer import phi
from utils import calculate_emotion_intensity

# Initialize text classifier
print("Loading classifier model ...")
classifier = pipeline(
    task="text-classification",
    model="SamLowe/roberta-base-go_emotions",
    top_k=None
)
print("Classifier loaded.")

async def process_user_input():
    loop = asyncio.get_running_loop()
    # loop until main flips the flag
    while simulation.running_flag.value:
        user_text = await loop.run_in_executor(None, input, "Enter your message (or type 'quit'): ")
        if user_text.lower() in ['quit', 'exit']:
            simulation.running_flag.value = False
            break

        # 1) Classification
        try:
            results = await loop.run_in_executor(None, classifier, user_text)
            if isinstance(results, list) and results and isinstance(results[0], list):
                results = results[0]
            best_pred = max(results, key=lambda x: x['score'])
            predicted_label = best_pred['label']
            print(f"Classifier predicted: {predicted_label} (score: {best_pred['score']:.3f})")
        except Exception as e:
            print("Error during classification:", e)
            predicted_label = None

        # 2) Current simulation‐based emotion
        with simulation.sim_lock:
            sims = [1 - cosine(simulation.global_M, d) for d in D]
            idx_sim = int(np.argmax(sims))
            print(f"Current emotion (simulation): {emotion_labels[idx_sim]}")

        # 3) Map and apply event
        mapped_label = None
        if predicted_label:
            for lab in emotion_labels:
                if lab.lower() == predicted_label.lower():
                    mapped_label = lab
                    break

        if mapped_label:
            idx = emotion_labels.index(mapped_label)
            occ_intensity = np.random.uniform(0, 1)

            # compute biases for printing
            norm_P = np.linalg.norm(P)
            norm_M = np.linalg.norm(simulation.global_M)
            norm_D = np.linalg.norm(D[idx])
            proj_P = np.dot(P, D[idx]) / (norm_P * norm_D) if norm_P and norm_D else 0.0
            proj_M = np.dot(simulation.global_M, D[idx]) / (norm_M * norm_D) if norm_M and norm_D else 0.0
            theta_P_i = TARGET_SHIFT * proj_P
            theta_M_i = TARGET_SHIFT * proj_M
            print(f"Personality bias (θ_P): {theta_P_i:.3f}, Mood bias (θ_M): {theta_M_i:.3f}")

            # calculate and apply
            I = calculate_emotion_intensity(occ_intensity, simulation.global_M, P, D[idx], TARGET_SHIFT)
            with simulation.sim_lock:
                simulation.global_M += alpha * phi[idx] * I * D[idx] * dt
                simulation.mood_history.append((asyncio.get_event_loop().time(), simulation.global_M.copy()))
            print(f"Applied {mapped_label}: intensity={I:.3f}")
        else:
            print("No mapping for classifier label; no event applied.")

        # 4) Send to GPT
        with simulation.sim_lock:
            sims = [1 - cosine(simulation.global_M, d) for d in D]
            idx_sim = int(np.argmax(sims))
            current_mood = emotion_labels[idx_sim]

        combined = f"(current mood: {current_mood})\n{user_text}"
        print("→ sending to GPT:", repr(combined))

