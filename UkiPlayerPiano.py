#!/usr/bin/env python
# -*- coding: utf_8 -*-
"""
 UkiPlayerPiano v0.1

 Chris Mock, 2017

 Sends motion sequences to UkiModbusManager.  Sequences are read from a CSV file in speed/accel format

 Licensed under GNU General Public License v3.0, https://www.gnu.org/licenses/gpl-3.0.txt

"""


#### Libs
import sys
import time
import socket
import yaml
import csv
from ModbusMap import MB_MAP

#### Config
IP_ADDRESS = '127.0.0.1'
OUTPUT_UDP_PORT = 9000
output_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet, UDP

DEFAULT_CONFIG_FILENAME = 'UkiConfig.json'

DEFAULT_FRAME_PERIOD = 0.500  # seconds frame duration
INTER_PACKET_DELAY = 0.015   # seconds between packet transmissions

#### Parse command line args
cmd_line_arg_count = len(sys.argv)
if cmd_line_arg_count < 2:
    print("Error: Provide the CSV filename on the command line")
    print("python UkiPlayerPiano.py <CSV filename> <Number of loops> <Frame period in milliseconds> <JSON Config filename>")
    sys.exit(5)

csv_filename = sys.argv[1]
loops = int(sys.argv[2]) if cmd_line_arg_count > 2 else 1
frame_period = (int(sys.argv[3]) / 1000) if cmd_line_arg_count > 3 else DEFAULT_FRAME_PERIOD
config_file_name = sys.argv[4] if cmd_line_arg_count > 4 else DEFAULT_CONFIG_FILENAME

print("*** UKI Player Piano ***")
print("CSV script input: " + csv_filename)
print("Loops: " + str(loops))
print("Frame period: " + str(frame_period * 1000) + "ms")
print("JSON config file: " + config_file_name + "\n")

#### Function definitions
def send_udp_command(address, offset, value):
    # Form UDP packet
    packet = [address, offset, value]
    # Convert to bytes
    packet = [entry.to_bytes(2, byteorder='little', signed=True) for entry in packet]
    # Flatten to byte string, ship out
    output_sock.sendto(b"".join(packet), (IP_ADDRESS, OUTPUT_UDP_PORT))
    time.sleep(INTER_PACKET_DELAY)

def send_reset_command(address):
    for reset_count in range(0, 3):
        send_udp_command(address, MB_MAP['MB_RESET_ESTOP'], 0x5050)

def send_setpoint_command(address, speed, accel):
    send_udp_command(address, MB_MAP['MB_MOTOR_SETPOINT'], speed)
    send_udp_command(address, MB_MAP['MB_MOTOR_ACCEL'], accel)


#### Read YAML config file, map names to addresses
print("Reading config file " + config_file_name + "...")
try:
    board_config = yaml.safe_load(open(config_file_name, 'r', encoding='utf8'))
except FileNotFoundError:
    print("Config file not found: " + config_file_name)
    sys.exit(1)
except yaml.parser.ParserError as exc:
    print("Failed to parse yaml config file:")
    print(exc)
    sys.exit(2)

board_names = []
board_mapping = {}
current_speed = {}
current_accel = {}
for cfg in board_config['actuators']:
    board_names.append(cfg['name'])
    board_mapping[cfg['name']] = cfg['address']
    current_speed[cfg['name']] = 0
    current_accel[cfg['name']] = 100

print("Found board names: " + str(board_names) + "\n")

#### Process CSV
try:

    # Reset all estop
    print("Resetting e-stop on all boards...")
    for board in board_mapping:
        send_reset_command(board_mapping[board])
    time.sleep(1)

    for loop_count in range(0, loops):
        print("\n* Starting loop " + str(loop_count + 1) + " of " + str(loops) + " *\n")

        with open(csv_filename, newline='') as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=',', quotechar='"')

            # Read header row
            print("Reading script file " + csv_filename + "...")
            header = next(csv_reader)
            print("Found columns: " + str(header) + "\n")
            try:
                actuator_names_by_col = [cell.split('_')[0] for cell in header]
                speed_accel = [cell.split('_')[1] for cell in header]
            except IndexError:
                print("Error: each column heading must have one underscore eg. LeftRearHip_Speed")
                sys.exit(3)

            # Loop over each remaining row in CSV
            print("Script running...")
            frame_number = 1
            for row in csv_reader:
                print("Frame " + str(frame_number) + " (row " + str(frame_number + 1) + ")")
                frame_number = frame_number + 1

                # Check for invalid row?

                # Loop over each cell in the row, process non-blank entries
                for cell_index in range(0, len(row)):
                    if row[cell_index] != '':
                        if speed_accel[cell_index] == 'Speed':
                            print("Set speed of " + actuator_names_by_col[cell_index] + " to " + row[cell_index])
                            current_speed[actuator_names_by_col[cell_index]] = int(row[cell_index])
                        elif speed_accel[cell_index] == 'Accel':
                            print("Set accel of " + actuator_names_by_col[cell_index] + " to " + row[cell_index])
                            current_accel[actuator_names_by_col[cell_index]] = int(row[cell_index])
                        else:
                            print("Warning: Invalid column name, does not contain '_Speed' or '_Accel'" + header[cell_index])
                            # Don't exit, need to fall thru to force stop

                for board in board_names:
                    # Range check inputs, warn?

                    # Always update every board, every frame
                    send_setpoint_command(board_mapping[board], current_speed[board], current_accel[board])

                time.sleep(frame_period)

    print("Script complete, sending stop commands...")

except KeyboardInterrupt:
    print("Caught keyboard interrupt, sending stop commands...")

#### Force stop message several times in case of dropped packets
for spam in range(0, 5):
    # Stop all boards
    for board in board_names:
        send_setpoint_command(board_mapping[board], 0, 100)
    time.sleep(frame_period)

output_sock.close()

print("Complete")

