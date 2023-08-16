
from os import environ
import argparse
import asyncio
import mido
import json
import re
import sys
import os
import time
import random
from spdsxpro_controller import SpdSxPro


class AbstractMidi:
    """ Used as an argument to SpdSxPro.init """

    def __init__(self):
        self.capture = ""

    def ensure_init_devices(self):
        pass

    def write_sys_ex(self, msg):
        self.capture = msg


def main():
    """
        Example:
          python3 spd_midi_formatter.py -d=17 ffffff 000000 110022
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', default=19, type=int, help="device_id")
    parser.add_argument('colors', nargs="*", type=str, help="colors")
    args = parser.parse_args()
    device_id = int(args.d)
    colors = args.colors

    print(f"Using device_id={device_id}")
    print(f"Colors={colors}")

    midi = AbstractMidi()
    spd = SpdSxPro(midi, device_id=device_id)

    for color in args.colors:
        #print(f'color:{color}')
        match = re.match(r"(?:0x|#)?([0-9a-f]{6})", color)
        if not match:
            print(f"skip invalid color string: \"{color}\"")
            continue
        rgb = int(match[1], 16)
        doc = [(rgb >> 16) & 0xff,
                (rgb >> 8) & 0xff,
                (rgb >> 0) & 0xff]
        spd.send_user_color(0, doc)

        msg = midi.capture
        msg = " ".join(f"{b:02x}" for b in msg)
        print(f'{color:8}: {str(doc):16}: {msg}')

if __name__ == '__main__':
    main()
