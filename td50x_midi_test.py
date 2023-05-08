# Suppress the hello message from PyGame
from os import environ
environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"  # Really!?

import sys
import os
import time
import pygame.midi
import mido

# https://www.pygame.org/docs/ref/midi.html#pygame.midi.Output.write_sys_ex
# Current Kit? Addr = 00 00 00 00


_MODEL_TD50X = [0, 0, 0, 0, 7]
_COMMAND_RQ1 = 0x11
_STATUS_SYSEX = 0xf0
_STATUS_EOX = 0xf7
_STATUS_TIMING_CLOCK = 0xf8
_STATUS_PROGRAM_CHANGE = 0xc9
_VENDOR_ID_ROLAND = 0x41
_DEVICE_ID = 0x10
_TARGET_DEVICE_NAME = "TD-50X"

def printSync(s, **kwargs):
    print(s)
    sys.stdout.flush()
    pass


def flatten(*args):
    out = []
    for a in args:
        if isinstance(a, list):
            out.extend(a)
        else:
            out.append(a)
    return out


def unpack4(arr):
    n = 0
    for x in arr:
        n = (n << 7) + x
    return n

def pack4(n):
    out = []
    for i in range(4):
        out.append((n >> 21) & 0x7f)
        n <<= 7
    return out


def checksum(arr):
    sum = 0
    for b in arr:
        sum += b
    return 128 - (sum % 128)


def prepare_sysex_msg(addr:int, size:int):
    """add the status fields and checksum to the message"""
    msg = flatten(
        _STATUS_SYSEX, _VENDOR_ID_ROLAND, _DEVICE_ID, _MODEL_TD50X, _COMMAND_RQ1
    )
    payload = []
    payload.extend(pack4(addr))
    payload.extend(pack4(size))
    msg.extend(payload)
    msg.append(checksum(payload))
    msg.append(_STATUS_EOX)
    #printSync(f'msg={[f"{x:02x}" for x in msg]}')
    return msg


def find_devices():
    """Find the TD-50X devices"""
    num_midi_devices = pygame.midi.get_count()
    printSync(f"Found {num_midi_devices} MIDI devices")
    printSync(f"Searching devices for name=[{_TARGET_DEVICE_NAME}]")
    input_device_id = None
    output_device_id = None
    for m in range(num_midi_devices):
        device_info = pygame.midi.get_device_info(m)
        if not device_info:
            continue
        iface, dname, is_input, is_output, opened = device_info
        dname = dname.decode(encoding="ascii")
        printSync(f"  [{m}] [{dname}] {is_input} {is_output}")
        if dname == _TARGET_DEVICE_NAME:
            if is_input == 1:
                input_device_id = m
            if is_output == 1:
                output_device_id = m
    if input_device_id is None or output_device_id is None:
        if input_device_id is None:
            printSync("No input device found")
        if output_device_id is None:
            printSync("No output device found")
        sys.exit(0)
    return input_device_id, output_device_id


def parse_sysex(buf) -> int:
    ok = True
    ok = ok or buf[0] == 0xf0
    ok = ok or buf[1] == 0x41
    dev = buf[2] 
    ok = ok or buf[3:8] == [0,0,0,0,7]
    ok = ok or buf[8] == 0x12
    addr = buf[9:13]
    data = buf[13:-2]
    sum = buf[-2]
    ok = ok or buf[-1] == 0xf7
    if not ok:
        return None
    addr = unpack4(addr)
    # s = "".join(s[13:-4])
    # s.decode(encoding="ascii")
    # printSync(f'{[f"{b:02x}" for b in buf]}')

    kit_offset = 0
    kit_name_start = 4 << 21
    kit_step = 2 << 14
    if addr == kit_offset:
        kit = int(data[0]) + 1
        #printSync(f"Current kit: {kit:03d}")
        return kit
    if addr > kit_name_start:
        kit = int((addr - kit_name_start) / kit_step)
        name = bytes(b & 0x7f for b in data[0:12]).decode(encoding='ascii')
        sub = bytes(b & 0x7f for b in data[12:12+15]).decode(encoding='ascii')
        name = name.rstrip(' ')
        sub = sub.rstrip(' ')
        printSync(f"{kit+1:03d}:[name:12]/[{sub}]")
        with open('kit.txt', 'w') as f:
            print(f"{kit+1:03d}:{name:12}\n{sub}", file=f)
        return None
    return None


# Initialize Midi
pygame.midi.init()

devices = find_devices()
printSync(f"Devices found: in=[{devices[0]}], out=[{devices[1]}]")
midi_input = pygame.midi.Input(devices[0])
midi_output = pygame.midi.Output(devices[1])

try:
    pending = None
    kit_init_index = 1
    sysex_response_buffer = None
    sent = False

    t_current_kit = time.time()

    while True:
        if pending is None and kit_init_index <= 100:
            #printSync(f"kit_init_index:{kit_init_index}")
            pending = kit_init_index
            kit_init_index += 1

        if pending is not None and not sent:
            #printSync(f"pending:{pending}")
            kit_addr = (4 << 21) + (pending - 1) * (2 << 14)
            msg = prepare_sysex_msg(kit_addr, 27)
            midi_output.write_sys_ex(0, msg)
            sent = True

        now = time.time()
        if t_current_kit is None or now - t_current_kit > 0.5:
            t_current_kit = now
            msg = prepare_sysex_msg(0, 1)
            midi_output.write_sys_ex(0, msg)

        for event in pygame.midi.Input.read(midi_input, 16):
            data, timestamp = event
            if sysex_response_buffer is not None:
                sysex_response_buffer.extend(data)
                if _STATUS_EOX in data:
                    pending = parse_sysex(sysex_response_buffer)
                    sysex_response_buffer = None
                    if pending is not None:
                        sent = False
            elif data[0] == _STATUS_SYSEX:
                sysex_response_buffer = data
            elif data[0] == _STATUS_TIMING_CLOCK:
                continue  # clock sync message
            elif data[0] == _STATUS_PROGRAM_CHANGE:
                # printSync(f'Kit changed to {data[1]+1:02d}')
                if pending is None:
                    pending = data[1] + 1
            else:
                #printSync(f'{[f"{d:02x}" for d in data]} {timestamp * 1e-3 : .3f}')
                pass
        time.sleep(0.001)

except KeyboardInterrupt:
    midi_output.close()
    midi_input.close()
    printSync("Keyboard Interrupt. Exiting")
