
# Suppress the hello message from PyGame
import pygame
from pygame.locals import *
import mido
import pygame.midi
import json
import sys
import os
import time

from os import environ
environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"  # so lame


def _printSync(msg: str, **kwargs):
    print(msg)
    sys.stdout.flush()


def _stringify(buf):
    return f"[{','.join([f'{d:02x}' for d in buf])}]"


class NoDeviceException (Exception):
    pass


class SpdSxPro:
    _device_name = "SPD-SX PRO"

    # confusing docs.. which is it?
    _MODEL_SPDSXPRO = [0x00, 0x00, 0x00, 0x00, 0x16]
    #_MODEL_SPDSXPRO = [0x00, 0x00, 0x00, 0x79]

    _COMMAND_RQ1 = 0x11
    _COMMAND_DT1 = 0x12

    _STATUS_SYSEX = 0xf0
    _STATUS_SYSEX_CHANNEL_BROADCAST = 0x7f
    _STATUS_TIMING_CLOCK = 0xf8
    _STATUS_PROGRAM_CHANGE = 0xc9
    _STATUS_NON_REALTIME = 0x7e
    _STATUS_EOX = 0xf7

    _VENDOR_ID_ROLAND = 0x41
    _DEVICE_ID = 0x10

    _STATUS_GENERAL_INFO = 0x06
    _STATUS_IDENTITY_REQUEST = 0x01
    _STATUS_IDENTITY_REPLY = 0x02

    _IDENTITY_REQUEST_MSG = [_STATUS_SYSEX,
                             _STATUS_NON_REALTIME,
                             _STATUS_SYSEX_CHANNEL_BROADCAST,
                             _STATUS_GENERAL_INFO,
                             _STATUS_IDENTITY_REQUEST,
                             _STATUS_EOX]

    def __init__(self):
        self.sysex_response_buffer = None
        self.t0 = None
        self.identityRequested = False
        self.identity = None
        self.devices = None
        self.midi_input = None
        self.midi_output = None
        pygame.midi.init()

    def done(self):
        return self.identity is not None


    @staticmethod
    def flatten(*args):
        out = []
        for a in args:
            if isinstance(a, list):
                out.extend(a)
            else:
                out.append(a)
        return out

    @staticmethod
    def unpack4(arr):
        n = 0
        for x in arr:
            n = (n << 7) + x
        return n

    @staticmethod
    def pack_bit_runs(val: int, grouping: int, width: int):
        """ pack each grouping of bits val into a byte, msn first, producing `width` bytes """
        out = []
        mask = (1 << grouping) - 1
        for i in range(width):
            out.append((val >> (grouping * (width - 1 - i))) & mask)
        return out

    @staticmethod
    def pack_nybbles(val: int, width: int):
        """ pack each nybble of val into a byte, msn first, producing `width` bytes """
        return SpdSxPro.pack_bit_runs(val, 4, width)

    @staticmethod
    def pack4(val: int):
        return SpdSxPro.pack_bit_runs(val, 7, 4)

    @staticmethod
    def checksum(arr):
        sum = 0
        for b in arr:
            sum += b
        return 128 - (sum % 128)

    def format_rq1_message(self, addr: int, size: int):
        msg = self.flatten(
            self._STATUS_SYSEX,
            self._VENDOR_ID_ROLAND,
            self.identity['dev'],
            self._MODEL_SPDSXPRO,
            self._COMMAND_RQ1
        )
        payload = []
        payload.extend(self.pack4(addr))
        payload.extend(self.pack4(size))
        msg.extend(payload)
        msg.append(self.checksum(payload))
        msg.append(self._STATUS_EOX)
        return msg

    def format_dt1_message(self, addr: int, data: bytearray):
        msg = self.flatten(
            self._STATUS_SYSEX,
            self._VENDOR_ID_ROLAND,
            self.identity['dev'],
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

    def find_devices(self, name: str):
        """Find the TD-50X devices"""
        num_midi_devices = pygame.midi.get_count()
        _printSync(f"Found {num_midi_devices} MIDI devices")
        _printSync(f"Searching devices for name=[{name}]")

        input_device_id = None
        output_device_id = None
        for dev in range(num_midi_devices):
            device_info = pygame.midi.get_device_info(dev)
            if not device_info:
                continue
            _, dname, is_input, is_output, _ = device_info
            dname = dname.decode(encoding="ascii")
            io = []
            if is_input:
                io.append("In")
            if is_output:
                io.append("Out")
            _printSync(f"  [{dev}] [{dname}] [{','.join(io)}]")
            if dname != name:
                continue
            if not input_device_id and is_input == 1:
                input_device_id = dev
            if not output_device_id and is_output == 1:
                output_device_id = dev

        if input_device_id is None:
            raise NoDeviceException(f'No input device named "{name}"')
        if output_device_id is None:
            raise NoDeviceException(f'No output device named "{name}"')
        return {'in': input_device_id, 'out': output_device_id}

    def init_devices(self):
        """ init """
        if self.midi_input:
            self.midi_input.close()
            self.midi_input = None
        if self.midi_output:
            self.midi_output.close()
            self.midi_output = None
        pygame.midi.quit()
        pygame.midi.init()
        if self.devices is None:
            self.devices = self.find_devices(self._device_name)
            _printSync(f"Devices: in=[{self.devices['in']}], out=[{self.devices['out']}]")
        self.midi_input = pygame.midi.Input(self.devices['in'])
        self.midi_output = pygame.midi.Output(self.devices['out'])

    def parse_sysex(self, buf) -> dict:
        """ interpret buf as a SysEx message """
        while len(buf) > 0 and buf[-1] == 0:
            buf.pop()
        if buf[0] != self._STATUS_SYSEX or buf[-1] != self._STATUS_EOX:
            _printSync(
                f'SysEx response formatting error: {_stringify(buf)}')
            return None
        buf = buf[1:-1]  # chomp SysEx framing bytes
        msg_type, dev, sub1, sub2 = buf[0:4]
        buf = buf[4:]
        if msg_type == self._STATUS_NON_REALTIME:
            if sub1 == self._STATUS_GENERAL_INFO:
                if sub2 == self._STATUS_IDENTITY_REPLY:
                    # manufacturer ID (Roland) [1]
                    # manufacturer Device family [2]
                    # manufacturer Device number [2]
                    # Software revision level [4]
                    obj = {
                        'identity': {
                            'dev': dev,
                            'manufacturer': buf[0],
                            'family': buf[1:3],
                            'model': buf[3:5],
                            'version': buf[5:9],
                        }
                    }
                    _printSync(json.dumps(obj, indent=4))
                    self.identity = obj['identity']
                    return obj
        return None

    def write_sysex(self, msg):
        self.init_devices()
        while len(msg) % 4 > 0:
            msg.append(0x0)  # pad to 4
        _printSync(f'write_sysex(msg={_stringify(msg)})')
        self.midi_output.write_sys_ex(0, msg)


    def demo(self):
        """ Ripped from midi impl pdf
            Requesting transmission of the output for the PAD1 of kit number 1
        """
        # model_id = [0x00, 0x00, 0x00, 0x00, 0x16]
        model_id = [0x00, 0x00, 0x00, 0x76]
        msg = self.flatten(0xF0, 0x41,
                           self.identity['dev'],
                           model_id,
                           0x11, 0x04, 0x00, 0x28, 0x0E, 0x00, 0x00, 0x00, 0x01, 0x45, 0xF7)
        self.write_sysex(msg)

    def send_dt1_poke(self, addr: int, data: bytearray):
        addr_buf = self.pack4(addr)
        _printSync(
            f"send_dt1_poke(addr={_stringify(addr_buf)}, data={_stringify(data)})")
        msg = self.format_dt1_message(addr, data)
        self.write_sysex(msg)

    def get_current_kit(self):
        addr = self.unpack4([0x00, 0x00, 0x00, 0x00])
        msg = self.format_rq1_message(addr, 4)
        self.write_sysex(msg)

    def set_user_color(self, idx: int, rgb: tuple[int, int, int]):
        # Set a sample pad user color value
        # Parameter Address Map:
        # [01 00 00 00]: Setup : [Setup]
        # [Setup]
        #     [08 00]: Color Table 1  : [SetupColor]
        #     [09 00]: Color Table 2  : [SetupColor]
        #     ...
        #     [17 00]: Color Table 16 : [SetupColor]
        # [SetupColor]
        #     [00]: name [16]
        #     [10]: R[4]  [0x00,0xff]  (split nybble format)
        #     [14]: G[4]  [0x00,0xff]  (split nybble format)
        #     [18]: B[4]  [0x00,0xff]  (split nybble format)
        # split nybble format e.g.:
        #     [0xab] is encoded as [0x0a, 0x0b]
        ###

        # address layout constants derived from the above spec
        setup_start = self.unpack4([0x01, 0x00, 0x00, 0x00])
        setup_color_table_start = self.unpack4([0x08, 0x00])
        setup_color_table_step = self.unpack4([0x01, 0x00])
        setup_color_rgb = self.unpack4([0x10])

        color_id = [10, 11, 12, 13, 14][idx]  # choose from user color ids

        addr = 0

        addr += setup_start + setup_color_table_start + \
            color_id * setup_color_table_step + setup_color_rgb

        data = []
        data.extend(self.pack_nybbles(rgb[0], 4))
        data.extend(self.pack_nybbles(rgb[1], 4))
        data.extend(self.pack_nybbles(rgb[2], 4))

        colorHex = '(' + ','.join([f'{x:02x}' for x in rgb]) + ')'
        _printSync(f"Set user color {color_id} to {colorHex}")
        self.send_dt1_poke(addr, data)

    def resetIdentity(self):
        self.identityRequested = False

    def loop(self):
        """ Loop """
        now = time.time()
        if not self.identityRequested:
            msg = self._IDENTITY_REQUEST_MSG
            self.write_sysex(msg)
            self.t0 = now
            self.identityRequested = True
            self.sysex_response_buffer = []
            return True

        if self.identityRequested and not self.identity and now - self.t0 > 5:
            self.identityRequested = False
            return True

        for event in pygame.midi.Input.read(self.midi_input, 16):
            data, _ = event
            _printSync(f'in: {_stringify(data)}')
            if self.sysex_response_buffer is not None:
                self.sysex_response_buffer.extend(data)
                if self._STATUS_EOX in data:
                    # Full sysex packet
                    self.parse_sysex(self.sysex_response_buffer)
                    self.sysex_response_buffer = None
                    #self.reconnect_midi()
        return True


class SpdSxProGui:
    _FPS = 60

    _COLORS = {
        '0': (0x00, 0x00, 0x00),  # black
        '1': (0xff, 0x00, 0x00),  # red
        '2': (0x00, 0xff, 0x00),  # green
        '3': (0x00, 0x00, 0xff),  # blue
        '4': (0x00, 0xff, 0xff),  # cyan
        '5': (0xff, 0xff, 0x00),  # yellow
        '6': (0xff, 0x00, 0xff),  # purple
        '7': (0xff, 0xff, 0xff),  # white
    }

    def __init__(self):
        pygame.init()
        self.clock = pygame.time.Clock()

        self.spd = SpdSxPro()
        self.user_colors = ['0', '0', '0', '0', '0']
        try:
            self.spd.init_devices()
        except NoDeviceException as ex:
            _printSync(ex)
            sys.exit(1)

        self.running = True
        self.screen = pygame.display.set_mode((640, 480))

        pygame.display.set_caption('SPD-SX PRO midi control')

    def draw(self):
        pos = pygame.Vector2(self.screen.get_width(), self.screen.get_height())
        pos = pos / 2
        dotColor = self._COLORS[self.user_colors[0]]
        pygame.draw.circle(self.screen, dotColor, pos, 40)

    def _set_user_color(self, user_color_index: int, key: str):
        """ Rewrite a user color
            user_index [0,4] which user color to adjust
        """
        if key not in self._COLORS:
            return
        if key != self.user_colors[user_color_index]:
            self.spd.set_user_color(user_color_index, self._COLORS[key])
        self.user_colors[user_color_index] = key

    def stop(self):
        self.running = False
        if pygame.midi.get_init():
            pygame.midi.quit()
        pygame.quit()
        raise SystemExit

    def get_current_kit(self):
        self.spd.get_current_kit()

    def run(self):
        _printSync('Press # keys for colors')
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.stop()
                if event.type == KEYDOWN:
                    try:
                        key = chr(event.key)
                    except ValueError:
                        continue
                    if key == 'q':
                        self.stop()
                    if key == 'k':
                        self.get_current_kit()
                    if key == 'd':
                        self.spd.demo()
                    if key == 'i':
                        self.spd.resetIdentity()
                    else:
                        # TODO support more color indexes
                        user_color_idx = 0
                        self._set_user_color(user_color_idx, key)
            self.spd.loop()
            self.draw()
            pygame.display.flip()
            dt = self.clock.tick(self._FPS) / 1000  # convert msec to sec


SpdSxProGui().run()
