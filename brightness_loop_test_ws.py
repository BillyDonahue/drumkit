# pylint: disable=W0621
"""Asynchronous Python client for WLED.

This one uses websockets

"""


import asyncio
import click
import rtmidi
import time
import websockets

class WledConnection:
    def __init__(self, uri : str):
        self.t0 = time.time()
        self.uri = uri
        self.bg_tasks = set()
        self.workload = asyncio.Queue()

    def now(self):
        return time.time() - t0

    async def worker(self):
        while True:
            print(f'worker awaiting a task')
            task = await self.workload.get()
            print(f'worker got a task')
            self.workload.task_done()
            print(f'worker finished a task')
        

    async def connect(self):
        print(f"connect('{self.uri}')")
        async for connection in websockets.connect(self.uri):
            print(f"connected {self.uri}")
            while True:
                message = await connection.recv()
                print(f'message: {message}')
        print(f"return from connect")

    async def run(self):
        self.bg_tasks.add(asyncio.create_task(self.connect()))
        self.bg_tasks.add(asyncio.create_task(self.worker()))
        await asyncio.gather(*self.bg_tasks, return_exceptions=True)
        await self.workload.join()

async def async_main() -> None:
    wled = WledConnection('ws://wled-1.local/ws')
    await wled.run()
    print(f"Awaiting asyncio.Future")
    await asyncio.Future()  # run forever

@click.command
def main() -> None:
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
