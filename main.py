import asyncio
import threading
from multiprocessing import Manager

import simulation
from processing import process_user_input
from kafka_integration import forward_messages

async def main():
    kafka_thread = threading.Thread(
        target=lambda: forward_messages(simulation.running_flag),
        daemon=False
    )
    kafka_thread.start()

    sim_thread = threading.Thread(target=simulation.update_mood, daemon=True)
    sim_thread.start()

    await process_user_input()

    sim_thread.join()
    kafka_thread.join()

    print("All threads have shut down. Goodbye!")

if __name__ == '__main__':
    manager = Manager()
    simulation.mood_history   = manager.list()
    simulation.running_flag   = manager.Value('b', True)

    asyncio.run(main())
