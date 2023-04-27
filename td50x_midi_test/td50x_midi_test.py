# Suppress the hello message from PyGame
from os import environ

environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import sys
import os
import time
import pygame.midi

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


def flatten(*args):
    out = []
    for a in args:
        if isinstance(a, list):
            out.extend(a)
        else:
            out.append(a)
    return out


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


def prepare_sysex_msg(addr, size):
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
    #print(f'msg={[f"{x:02x}" for x in msg]}')
    return msg


def find_devices():
    """Find the TD-50X devices"""
    num_midi_devices = pygame.midi.get_count()
    print(f"Found {num_midi_devices} MIDI devices")
    print(f"Searching devices for name=[{_TARGET_DEVICE_NAME}]")
    input_device_id = None
    output_device_id = None
    for m in range(num_midi_devices):
        device_info = pygame.midi.get_device_info(m)
        if not device_info:
            continue
        iface, dname, is_input, is_output, opened = device_info
        dname = dname.decode(encoding="UTF-8")
        print(f"  [{m}] [{dname}] {is_input} {is_output}")
        if dname == _TARGET_DEVICE_NAME:
            if is_input == 1:
                input_device_id = m
            if is_output == 1:
                output_device_id = m
    if input_device_id is None or output_device_id is None:
        if input_device_id is None:
            print("No input device found")
        if output_device_id is None:
            print("No output device found")
        sys.exit(0)
    return input_device_id, output_device_id


def parse_sysex(kit, buf):
    s = "".join(chr(b) for b in buf[13:-4])
    # print(f'{[f"{b:02x}" for b in buf]}')
    print(f"{kit+1:03d} : {s}")


# Initialize Midi
pygame.midi.init()

devices = find_devices()
print(f"Devices found: in=[{devices[0]}], out=[{devices[1]}]")
midi_input = pygame.midi.Input(devices[0])
midi_output = pygame.midi.Output(devices[1])

# current_kit_sysex_msg = prepare_sysex_msg(0, 1)

try:
    pending = None
    kit_init_index = 0
    sysex_response_buffer = None
    sent = False

    while True:
        if pending is None and kit_init_index < 100:
            #print(f"kit_init_index:{kit_init_index}")
            pending = kit_init_index
            kit_init_index += 1

        if pending is not None and not sent:
            time.sleep(0.1)
            #print(f"pending:{pending}")
            kit_addr = (4 << 21) + pending * (2 << 14)
            msg = prepare_sysex_msg(kit_addr, 27)
            midi_output.write_sys_ex(0, msg)
            sent = True

        # read one event
        event_list = pygame.midi.Input.read(midi_input, 1)
        if len(event_list) == 0:
            continue
        for event in event_list:
            data, timestamp = event
            if sysex_response_buffer is not None:
                sysex_response_buffer.extend(data)
                if _STATUS_EOX in data:
                    parse_sysex(pending, sysex_response_buffer)
                    sysex_response_buffer = None
                    pending = None
                    sent = False
            elif data[0] == _STATUS_SYSEX:
                sysex_response_buffer = data
            elif data[0] == _STATUS_TIMING_CLOCK:
                continue  # clock sync message
            elif data[0] == _STATUS_PROGRAM_CHANGE:
                print(f'Kit changed to {data[1]+1:02d}')
                if pending is None:
                    pending = data[1]
            else:
                print(f'{[f"{d:02x}" for d in data]} {timestamp * 1e-3 : .3f}')

except KeyboardInterrupt:
    midi_output.close()
    midi_input.close()
    print("Keyboard Interrupt. Exiting")
