# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio
import time

from wled import WLED, Playlist, Preset

t0 = time.time()

def now():
    return time.time() - t0

async def main() -> None:
    """Show example on controlling your WLED device."""
    async with WLED("wled-1.local") as led:
        device = await led.update()
        print(device.info.version)

        if isinstance(device.state.preset, Preset):
            print(f"Preset active! Name: {device.state.preset.name}")

        if isinstance(device.state.playlist, Playlist):
            print(f"Playlist active! Name: {device.state.playlist.name}")

        await led.master(on=True)

        while True:
            t0 = time.time()
            # Turn strip on, ramp brightness
            for br in range(0, 255, 8):
                then = now()
                setting = {'brightness': br}
                await led.master(**setting)
                t = now()
                print(f't={t:9.3f}: dt={t-then:9.3f}: setting={setting}')
                await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
