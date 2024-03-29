from os import environ
# Suppress the hello message from PyGame
environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"  # so lame

import argparse
import asyncio
import pygame
from pygame.locals import *
import mido
import pygame.midi
from paho.mqtt import client as mqtt_client
import json
import sys
import os
import time
import random
import queue
from websockets.server import serve

# Example:
# Run a mosquitto server on localhost.
# Then configure Lumia Stream to push events like this:
#   {"colors":[[255,128,0]]}
# to the "spdsxpro" topic


class NoDeviceException (Exception):
    pass


class MqttListener:
    def __init__(self, broker: str, port: int, topic: str, queue: queue.SimpleQueue):
        self.broker = broker
        self.port = port
        self.topic = topic
        self.queue = queue
        self.client_id = f'python-mqtt-{random.randint(0, 1000)}'
        self.client = None  # need to connect

    def connect(self):
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print(f"MQTT: Connected")
            else:
                print(f"MQTT: Failed({rc})\n")
        self.client = mqtt_client.Client(self.client_id)
        self.client.user_data_set(self)
        self.client.on_connect = on_connect
        print(f"MQTT: Connecting to {self.broker}:{self.port}")
        self.client.connect(self.broker, self.port)
        return self.client

    def subscribe(self):
        def on_message(client, userdata, msg):
            payload = msg.payload.decode()
            try:
                doc = json.loads(payload)
            except json.JSONDecodeError as ex:
                print(f"MQTT: json decode error msg={payload}, ex={ex}")
                return

            print(f"MQTT: topic={msg.topic}: msg={doc}")
            userdata.queue.put(doc)

        self.client.on_message = on_message
        self.client.subscribe(self.topic)
        print(f"MQTT: Subscribed to `{self.topic}`")

    def start(self):
        self.client.loop_start()

    def poll(self):
        try:
            return self.queue.get(block=False)
        except queue.Empty:
            return None


class AbstractMidi:
    """ Used as an argument to SpdSxPro.init """

    # Something weird with macOS, pygame.midi, or the SPD-SX PRO itself?
    # Can only get one command in, and the connection stops working.
    _RECONNECT_MIDI_PER_COMMAND = True

    def __init__(self, midi_connection_name: str):
        self.midi_connection_name = midi_connection_name
        self.midi_output = None
        pygame.midi.init()

    def ensure_init_devices(self):
        """ init """
        is_init = pygame.midi.get_init()
        if self._RECONNECT_MIDI_PER_COMMAND and is_init:
            if self.midi_output:
                self.midi_output.close()
                self.midi_output = None
            pygame.midi.quit()
            is_init = False

        if not is_init:
            pygame.midi.init()

        if self.midi_output is None:
            dev = self.find_output_device(self.midi_connection_name)
            self.midi_output = pygame.midi.Output(dev, latency=0)

    def write_sys_ex(self, msg):
        hex = " ".join(f"{b:02x}" for b in msg)
        print(f'write_sys_ex([{hex}])')
        self.ensure_init_devices()
        while len(msg) % 4 > 0:
            msg.append(0)  # pad to 4
        self.midi_output.write_sys_ex(0, msg)

    def find_output_device(self, name: str):
        """ Find the output device called `name` """
        num_midi_devices = pygame.midi.get_count()
        for idx in range(num_midi_devices):
            device_info = pygame.midi.get_device_info(idx)
            if not device_info:
                continue
            _, device_name, _, is_output, _ = device_info
            device_name = device_name.decode(encoding="ascii")
            if device_name == name and is_output == 1:
                return idx
        raise NoDeviceException(f'No output device named "{name}"')


class SpdSxPro:
    _STATUS_SYSEX = 0xf0
    _STATUS_EOX = 0xf7
    _COMMAND_DT1 = 0x12
    _VENDOR_ID_ROLAND = 0x41
    _MODEL_SPDSXPRO = [0x00, 0x00, 0x00, 0x00, 0x16]

    # Address layout constants from the SPD-SX PRO MIDI impl doc.
    _SETUP_START = [0x01, 0x00, 0x00, 0x00]
    _COLOR_TABLE_START = [0x08, 0x00]
    _COLOR_TABLE_STEP = [0x01, 0x00]
    _COLOR_TABLE_RGB = [0x10]

    # Palette positions of user colors 1 through 5
    _USER_PALETTE_INDICES = [10, 11, 12, 13, 14]

    def __init__(self, midi: AbstractMidi, device_id: int):
        self.midi = midi
        self.device_id = device_id

    @staticmethod
    def _flatten(*args):
        out = []
        for a in args:
            if isinstance(a, list):
                out.extend(a)
            else:
                out.append(a)
        return out

    @staticmethod
    def _unpack4(arr):
        n = 0
        for x in arr:
            n = (n << 7) + x
        return n

    @staticmethod
    def _pack_bit_runs(val: int, grouping: int, width: int):
        """ pack each grouping of bits val into a byte, msn first, producing `width` bytes """
        out = []
        mask = (1 << grouping) - 1
        for i in range(width):
            out.append((val >> (grouping * (width - 1 - i))) & mask)
        return out

    @staticmethod
    def pack_nybbles(val: int, width: int):
        """ pack each nybble of val into a byte, msn first, producing `width` bytes """
        return SpdSxPro._pack_bit_runs(val, 4, width)

    @staticmethod
    def pack4(val: int):
        return SpdSxPro._pack_bit_runs(val, 7, 4)

    @staticmethod
    def checksum(arr):
        sum = 0
        for b in arr:
            sum += b
        return 128 - (sum % 128)

    def _format_dt1_message(self, addr: int, data: bytearray):
        msg = self._flatten(
            self._STATUS_SYSEX,
            self._VENDOR_ID_ROLAND,
            self.device_id - 1,
            self._MODEL_SPDSXPRO,
            self._COMMAND_DT1
        )
        payload = []
        payload.extend(self.pack4(addr))
        payload.extend(data)
        msg.extend(payload)
        msg.append(self.checksum(payload))
        msg.append(self._STATUS_EOX)
        return msg

    def send_user_color(self, user_color_index: int, rgb: tuple[int, int, int]):
        """ There are 5 user color slots to set """
        palette_index = self._USER_PALETTE_INDICES[user_color_index]

        setup_start = self._unpack4(self._SETUP_START)
        setup_color_table_start = self._unpack4(self._COLOR_TABLE_START)
        setup_color_table_step = self._unpack4(self._COLOR_TABLE_STEP)
        setup_color_rgb = self._unpack4(self._COLOR_TABLE_RGB)

        addr = 0
        addr += setup_start
        addr += setup_color_table_start
        addr += palette_index * setup_color_table_step
        addr += setup_color_rgb

        data = []
        data.extend(self.pack_nybbles(rgb[0], 4))
        data.extend(self.pack_nybbles(rgb[1], 4))
        data.extend(self.pack_nybbles(rgb[2], 4))

        msg = self._format_dt1_message(addr, data)

        self.midi.write_sys_ex(msg)

class App:
    _FPS = 60

    def __init__(self, options):
        self.queue = queue.SimpleQueue()
        self.mqtt = MqttListener(broker=options.a,
                                 port=options.p,
                                 topic=options.t,
                                 queue=self.queue)
        self.mqtt.connect()
        self.mqtt.subscribe()
        midi = AbstractMidi(options.i)
        self.spd = SpdSxPro(midi, device_id=options.d)

    def get_current_kit(self):
        self.spd.get_current_kit()

    def run(self):
        self.mqtt.start()
        while True:
            doc = self.mqtt.poll()
            if doc is not None:
                print(f'doc={doc}')
                arr = doc['colors']
                for i in range(len(arr)):
                    try:
                        self.spd.send_user_color(i, rgb = doc['colors'][i])
                    except Exception as ex:
                        print(f"Exception sending color to sample pad: {ex}")
            time.sleep(1. / self._FPS)

def main():
    """main"""
    parser = argparse.ArgumentParser()
    for opt, val, type, help in [
        ('-a', 'localhost', str, 'MQTT broker IP'),
        ('-p', 1883, int, 'MQTT broker port'),
        ('-t', "spdsxpro", str, 'MQTT topic'),
        ('-i', "SPD-SX PRO", str, 'MIDI connection name'),
        ('-d', 19, int, 'SPD-SX PRO MIDI device id'),
    ]:
        parser.add_argument(opt, default=val, help=help)
    args = parser.parse_args()
    print(str(args))
    App(args).run()

if __name__ == '__main__':
    main()
