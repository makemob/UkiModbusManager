#!/usr/bin/env python
# -*- coding: utf_8 -*-
"""
 Test socket comms to UkiModbusManager

 Chris Mock, 2017

 Licensed under GNU General Public License v3.0, https://www.gnu.org/licenses/gpl-3.0.txt
"""

import socket

import time

import sys

IP_ADDRESS = '127.0.0.1'
OUTPUT_UDP_PORT = 9000

ENABLED_BOARDS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] #, 22, 23, 25, 26]

output_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet, UDP


# for speed in [10, 0, -10]:
#   for board in ENABLED_BOARDS:

# Prepare packet, interleaving reg offset and reg value (effectively key-value pairs)
# First two bytes are the modbus address
packet = [int(sys.argv[1])]
packet.append(int(sys.argv[2]))
packet.append(int(sys.argv[3]))
#packet = [board, 200, speed]

print(packet)

# Convert to bytes
packet = [entry.to_bytes(2, byteorder='little', signed=True) for entry in packet]

print(packet)

# Flatten to byte string, ship out
#for loop in range(5):
output_sock.sendto(b"".join(packet), (IP_ADDRESS, OUTPUT_UDP_PORT))

print(b"".join(packet))

# time.sleep(3)

output_sock.close()
