import asyncio
import threading
from multiprocessing import Manager
import simulation
from processing import process_user_input

async def main():

    # 2) Start the mood simulation thread
    sim_thread = threading.Thread(target=simulation.update_mood, daemon=True)
    sim_thread.start()

    # 4) Enter user‐input loop
    await process_user_input()

    # 5) Cleanup
    sim_thread.join()
    simulation.running_flag.value = False
    print("Simulation ended.")

if __name__ == '__main__':
    manager = Manager()
    shared_mood_history = manager.list()
    simulation.mood_history = shared_mood_history
    simulation.running_flag = manager.Value('b', True)

    # Run the async main
    asyncio.run(main())