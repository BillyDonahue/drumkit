#Suppress the hello message from PyGame
from os import environ
environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import sys
import os
import time
import pygame.midi

#https://www.pygame.org/docs/ref/midi.html#pygame.midi.Output.write_sys_ex
# Current Kit? Addr = 00 00 00 00
# SetList starting addr = 03 00 00 00
def print_msg(msg):
    new_msg = []
    for x in range(0, len(msg)):
        new_msg.append(hex(msg[x]))
    print(new_msg)
        

#add the status fields and checksum to the message
def prepare_sysex_msg(addr, data):
    prepared_msg = [0xF0, 0x41, 0x10, 0x00, 0x00, 0x00, 0x00, 0x07, 0x11]
    sum = 0
    for byte in addr:
        sum += byte
        prepared_msg.append(byte)
    for byte in data:
        sum += byte
        prepared_msg.append(byte)
    checksum = 128 - (sum % 128)
    prepared_msg.append(checksum)
    prepared_msg.append(0xF7)
    print_msg(prepared_msg)
    return prepared_msg 
        
input_device_id = -1
output_device_id = -1
device_name = "TD-50X"

#Initialize Midi
pygame.midi.init()

#Find the TD-50X devices
num_midi_devices = pygame.midi.get_count()
print(f"Found {num_midi_devices} Midi Devices")
print(f"Searching devices for name=[{device_name}]")

for m in range(0, num_midi_devices):
    device_info = pygame.midi.get_device_info(m)
    if device_info is None:
        continue
    print(device_info[1].decode(encoding='UTF-8'))
    if device_info[1].decode(encoding='UTF-8') == device_name:
        if device_info[1] == 1:
            input_device_id = m
        if device_info[1] == 0:
            output_device_id = m

input_device_id = 0
output_device_id = 3

if input_device_id >= 0:
    print(f"Input Device Found: id=[{input_device_id}] name=[{device_name}]")
else:
    print("Input Device not found")
if output_device_id >= 0:
    print(f"Output Device Found: id=[{output_device_id}] name=[{device_name}]")
else:
    print("Output Device not found")
if input_device_id == -1 or output_device_id == -1:
    sys.exit(0)

midi_output = pygame.midi.Output(output_device_id)
current_kit_sysex_msg = prepare_sysex_msg([0x00, 0x00, 0x00, 0x00], [0x00, 0x00, 0x00, 0x01])
kitname_sysex_msg = prepare_sysex_msg([0x04, 0x00, 0x00, 0x00], [0x00, 0x00, 0x00, 0x1B])
midiInput = pygame.midi.Input(input_device_id)
sent = False
try:
    midi_output.write_sys_ex(0, kitname_sysex_msg)
    while(True): 
        midi_data = pygame.midi.Input.read(midiInput,1)
        if len(midi_data) > 0:
            print(midi_data)
except KeyboardInterrupt:
    midi_output.close()
    midiInput.close()
    print("Keyboard Interrupt. Exiting")