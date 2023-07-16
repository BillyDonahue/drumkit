
# Suppress the hello message from PyGame
import pygame
from pygame.locals import *
import mido
import pygame.midi
import time
import os
import sys
import json
from os import environ
environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"  # so lame


def _printSync(msg: str, **kwargs):
    print(msg)
    sys.stdout.flush()


def _stringifyBuf(buf):
    return f"[{','.join([f'{d:02x}' for d in buf])}]"


class NoDeviceException (Exception):
    pass


class SpdSxPro:
    _device_name = "SPD-SX PRO"

    _MODEL_SPDSXPRO = [0x00, 0x00, 0x00, 0x79]
    _COMMAND_RQ1 = 0x11

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
    def pack4(n):
        out = []
        for i in range(4):
            out.append((n >> 21) & 0x7f)
            n <<= 7
        return out

    @staticmethod
    def checksum(arr):
        sum = 0
        for b in arr:
            sum += b
        return 128 - (sum % 128)

    def prepare_sysex_msg(self, addr: int, size: int):
        """add the status fields and checksum to the message"""
        msg = self.flatten(
            self._STATUS_SYSEX,
            self._VENDOR_ID_ROLAND,
            self._DEVICE_ID,
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

    # RQ1
    # 0xf0
    # 0x41
    # dev
    #
    # model number: SPD-SX PRO
    # 0x00, 0x00, 0x00, 0x00, 0x16,
    #
    # 0x11
    #
    # aa
    # bb
    # cc
    # dd
    # ss
    # tt
    # uu
    # vv
    # sum
    # 0xf7

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
        return input_device_id, output_device_id

    def init_devices(self):
        """ init """
        self.devices = self.find_devices(self._device_name)
        _printSync(
            f"Devices found: in=[{self.devices[0]}], out=[{self.devices[1]}]")
        self.midi_input = pygame.midi.Input(self.devices[0])
        self.midi_output = pygame.midi.Output(self.devices[1])

    def parse_sysex(self, buf) -> dict:
        """ interpret buf as a SysEx message """
        while len(buf) > 0 and buf[-1] == 0:
            buf.pop()
        if buf[0] != self._STATUS_SYSEX or buf[-1] != self._STATUS_EOX:
            _printSync(
                f'SysEx response formatting error: {_stringifyBuf(buf)}')
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

    def send_dt1(self):
        pass

    def loop(self):
        """ Loop """
        now = time.time()
        if not self.identityRequested:
            msg = self._IDENTITY_REQUEST_MSG
            _printSync(f'writing request {_stringifyBuf(msg)}')
            self.midi_output.write_sys_ex(0, msg)
            self.t0 = now
            self.identityRequested = True
            self.sysex_response_buffer = []
            return True

        if self.identityRequested and not self.identity and now - self.t0 > 5:
            self.identityRequested = False
            return True

        for event in pygame.midi.Input.read(self.midi_input, 16):
            data, _ = event
            _printSync(f'in: {_stringifyBuf(data)}')
            if self.sysex_response_buffer is not None:
                self.sysex_response_buffer.extend(data)
                if self._STATUS_EOX in data:
                    # Full sysex packet
                    self.parse_sysex(self.sysex_response_buffer)
                    self.sysex_response_buffer = None
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
        pygame.midi.init()

        self.spd = SpdSxPro()
        self.color = '0'
        try:
            self.spd.init_devices()
        except NoDeviceException as ex:
            _printSync(ex)
            sys.exit(1)

        self.clock = pygame.time.Clock()
        self.running = True
        self.screen = pygame.display.set_mode((640, 480))

        pygame.display.set_caption('SPD-SX PRO midi control')

    def draw(self):
        pos = pygame.Vector2(self.screen.get_width(), self.screen.get_height())
        pos = pos / 2
        dotColor = self._COLORS[self.color]
        pygame.draw.circle(self.screen, dotColor, pos, 40)

    def _handleKeydown(self, event):
        _printSync(f"key pressed: {event.key}")
        ch = chr(event.key)
        if ch in self._COLORS:
            self.color = ch

    def run(self):
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    pygame.quit()
                    raise SystemExit
                if event.type == KEYDOWN:
                    self._handleKeydown(event)
            self.spd.loop()
            self.draw()
            pygame.display.flip()
            dt = self.clock.tick(self._FPS) / 1000  # convert msec to sec


SpdSxProGui().run()
