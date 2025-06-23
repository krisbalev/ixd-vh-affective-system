import asyncio, threading, signal
from multiprocessing import Manager
import kafka_integration as ki
import simulation
from processing import process_user_input

def shutdown(signum, frame):
    print("⚙️  Initiating graceful shutdown…")
    simulation.running_flag.value = False

signal.signal(signal.SIGINT,  shutdown)
signal.signal(signal.SIGTERM, shutdown)



async def main():
    # 1) Kafka consumer
    kafka_thread = threading.Thread(
        target=ki.run_consumer_loop,
        daemon=True
    )
    kafka_thread.start()

    # 2) Simulation updater
    sim_thread = threading.Thread(
        target=simulation.update_mood,
        daemon=True
    )
    sim_thread.start()

    # 3) Your async user‑input loop
    # await process_user_input()

    # 4) Wait for threads to finish
    kafka_thread.join()
    sim_thread.join()
    print("✅ All threads stopped. Exiting.")

if __name__ == '__main__':
    manager = Manager()
    simulation.mood_history = manager.list()
    simulation.running_flag = manager.Value('b', True)

    asyncio.run(main())
