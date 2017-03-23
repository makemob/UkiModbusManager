#!/usr/bin/env python
# -*- coding: utf_8 -*-
"""
 UkiModbusManager v0.2

 Chris Mock, 2017

 Licensed under GNU General Public License v3.0, https://www.gnu.org/licenses/gpl-3.0.txt

"""

#### Still to do: ####
# Read yaml config file (select board addresses, baud rate, modbus map etc.)
# Autoset config (current limits)
# Command line args


##### Libs #####
import serial

import modbus_tk
import modbus_tk.defines as cst
from modbus_tk import modbus_rtu

import logging
import socket
import time
import collections
import sys

##### Defines #####
LOG_LEVEL = logging.INFO

IP_ADDRESS = "127.0.0.1"
INPUT_UDP_PORT = 9000
OUTPUT_UDP_PORT = 9001

# SERIAL_PORT = '/dev/tty.usbserial-FTZ5B0HX'
SERIAL_PORT = '/dev/tty.usbserial-FTYSCI9K'
BAUD_RATE = 19200
TIMEOUT = 0.100  # seconds (typical response from Scarab 3ms)
MAX_RETRIES = 3

INCOMING_MSG_HEARTBEAT_TIMEOUT = 5  # Allowable seconds between incoming UDP messages before estop triggered

# // Modbus states that a baud rate higher than 19200 must use a fixed 750 us
# // for inter character time out and 1.75 ms for a frame delay.
# // For baud rates below 19200 the timeing is more critical and has to be calculated.
# // E.g. 9600 baud in a 10 bit packet is 960 characters per second
# // In milliseconds this will be 960characters per 1000ms. So for 1 character
# // 1000ms/960characters is 1.04167ms per character and finaly modbus states an
# // intercharacter must be 1.5T or 1.5 times longer than a normal character and thus
# // 1.5T = 1.04167ms * 1.5 = 1.5625ms. A frame delay is 3.5T.
# // Added sperimentally low latency delays. This makes the implementation
# // non-standard but practically it works with all major modbus master implementations.
INTER_FRAME_DELAY = 0.002  # 1.8ms used on Scarab board for 19200 baud, use 2ms as some inaccuracy at both ends..

ENABLED_BOARDS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 25, 26]
# ENABLED_BOARDS = [27] * 22
# ENABLED_BOARDS = [27]

# MAX_MOTOR_SPEED = 50  # max allowable motor speed %

MB_MAP = {
    'MB_SCARAB_ID1' : 0,

	'MB_BRIDGE_CURRENT' : 100,
	'MB_BATT_VOLTAGE' : 101,
	'MB_MAX_BATT_VOLTAGE' : 102,
	'MB_MIN_BATT_VOLTAGE' : 103,
	'MB_BOARD_TEMPERATURE' : 104,

	'MB_MOTOR_SETPOINT' : 200,
	'MB_MOTOR_SPEED' : 201,
	'MB_MOTOR_ACCEL' : 202,
	'MB_CURRENT_LIMIT_INWARD' : 203,
	'MB_CURRENT_LIMIT_OUTWARD' : 204,

	'MB_ESTOP' : 208,
	'MB_RESET_ESTOP' : 209,    # Write 0x5050 to reset emergency stop
	'MB_MOTOR_PWM_FREQ_MSW' : 210,
	'MB_MOTOR_PWM_FREQ_LSW' : 211,
	'MB_MOTOR_PWM_DUTY_MSW' : 212,
	'MB_MOTOR_PWM_DUTY_LSW' : 213,

    'MB_ESTOP_STATE': 300,
    'MB_CURRENT_TRIPS_INWARD': 301,
    'MB_CURRENT_TRIPS_OUTWARD': 302,
    'MB_INWARD_ENDSTOP_STATE': 303,
    'MB_OUTWARD_ENDSTOP_STATE': 304,
    'MB_INWARD_ENDSTOP_COUNT': 305,
    'MB_OUTWARD_ENDSTOP_COUNT': 306,
    'MB_VOLTAGE_TRIPS': 307,
    'MB_HEARTBEAT_EXPIRIES' : 308,

    'MB_HEARTBEAT_TIMEOUT' : 9008,  # seconds until heartbeat timer trips

    'MAX_MODBUS_OFFSET' : 9009
}

class UkiModbus:

    def __init__(self, serial_port, baud_rate, timeout, max_retries, interframe_delay):
        self.logger = modbus_tk.utils.create_logger("console", level=LOG_LEVEL)

        self.retries = max_retries
        self.interframe_delay = interframe_delay

        # Shadow modbus map, store values when read, use this to check if a write needs to be made
        self.shadow_map = dict([(address, collections.defaultdict(list)) for address in ENABLED_BOARDS])

        self.clear_write_queue()  # Initialises empty write queue

        try:
            self.mb_conn = modbus_rtu.RtuMaster(
                serial.Serial(port=serial_port, baudrate=baud_rate, bytesize=8, parity='N', stopbits=1, xonxoff=0)
            )
            self.mb_conn.set_timeout(timeout)
            if LOG_LEVEL == logging.DEBUG:
                self.mb_conn.set_verbose(True)
            self.logger.info("Modbus port " + serial_port)
        except modbus_tk.modbus.ModbusError as exc:
            self.logger.error("%s- Code=%d", exc, exc.get_exception_code())

    def clear_write_queue(self):
        self.write_queue = dict([(address, list()) for address in ENABLED_BOARDS])

    def access_regs(self, command, address, start_offset, end_offset, write_data = 0):
        """Read multiple holding regs (inclusive), write single holding reg"""
        response = None
        retry_count = 0
        while (response == None) and (retry_count < self.retries):
            try:
                response = self.mb_conn.execute(address, command, start_offset, end_offset - start_offset + 1, output_value=write_data)
            except modbus_tk.modbus.ModbusError as exc:
                self.logger.error("%s- Code=%d", exc, exc.get_exception_code())
            except modbus_tk.modbus.ModbusInvalidResponseError as exc:
                retry_count = retry_count + 1
                self.logger.warning("Invalid response %s, retry %d", exc, retry_count)
                # raise  # remove to catch all
                if (retry_count >= self.retries):
                    self.logger.error("Max retries exceeded for address " + str(address) + ", offsets " + str(start_offset) + " - " + str(end_offset))
                    # raise # remove to catch all
            except Exception as exp:
                self.logger.error(exp)
                print(exp)
                raise # remove to catch all

        time.sleep(self.interframe_delay)

        return(response)

    def read_regs(self, address, start_offset, end_offset):
        """Read multiple holding regs (inclusive)"""
        return(self.access_regs(cst.READ_HOLDING_REGISTERS, address, start_offset, end_offset))

    def write_reg(self, address, offset, value):
        """Write single holding reg"""
        return (self.access_regs(cst.WRITE_SINGLE_REGISTER, address, offset, offset, write_data=value))




##### Functions #####

def query_and_forward(modbus, output_socket, address, start_offset, end_offset):
    """Read modbus reg(s), send to output socket"""
    modbus.logger.debug("Reading from address " + str(address) + ", from offset " + str(start_offset) + " to " + str(end_offset))

    regs = modbus.read_regs(address, start_offset, end_offset)

    if (regs != None):
        # Prepare packet, interleaving reg offset and reg value (effectively key-value pairs)
        # First two bytes are the modbus address
        packet = [address]
        # Then loop over each register, appending to the byte string
        for pos in range(len(regs)):
            # Next the register offset (2 bytes)
            packet.append(start_offset + pos)
            # The next two bytes are the register value
            packet.append(regs[pos])
            # Store the response in shadow modbus map
            modbus.shadow_map[address][start_offset + pos] = regs[pos]
    else:
        # Modbus error occurred
        # Error packets use 10000 register block
        #  - address (2 bytes)
        #  - 10000 (2 bytes)
        #  - start_offset (2 bytes)
        #  - 10001 (2 bytes)
        #  - end_offset (2 bytes)
        packet = [address, 10000, start_offset, 10001, end_offset]
        # Clear regs in shadow modbus map
        for offset in range(start_offset, end_offset + 1):
            modbus.shadow_map[address][offset] = None

    # Convert to bytes
    packet = [entry.to_bytes(2, byteorder='little') for entry in packet]

    # Flatten to byte string, ship out
    output_socket.sendto(b"".join(packet), (IP_ADDRESS, OUTPUT_UDP_PORT))

def estop_all_boards(modbus):
    """Queue an estop command to all boards"""
    modbus.logger.warning("Sending e-stop to all boards")
    for estop_address in ENABLED_BOARDS:
        modbus.write_queue[estop_address].append((MB_MAP['MB_ESTOP'], 1))

def process_incoming_packet(modbus, input_socket):
    """Check for incoming UDP packets, parse and store contents in write queue"""

    valid_msg_received = False

    while True:
        try:
            (incoming_packet, input_address) = input_socket.recvfrom(65535)

            modbus.logger.debug("Received" + str(len(incoming_packet)) + "bytes via UDP")

            if ((len(incoming_packet) % 2) != 0):
                modbus.logger.error("Received incorrectly formatted UDP packet", str(incoming_packet))
                # No UDP response for malformed packets
            else:
                modbus.logger.info(incoming_packet)

                # Extract write address (first two bytes)
                write_address = int.from_bytes(incoming_packet[0:2], byteorder='little', signed=False)

                if write_address not in ENABLED_BOARDS + [0]:
                    modbus.logger.warning("Received message for board that is not enabled: " + str(write_address))
                else:
                    # Step through the rest of the packet four bytes at a time (ie. break down into offset/value pairs)
                    for pos in range(2, len(incoming_packet), 4):
                        write_offset = int.from_bytes(incoming_packet[pos:(pos + 2)], byteorder='little', signed=False)
                        write_value = int.from_bytes(incoming_packet[(pos + 2):(pos + 4)], byteorder='little',
                                                     signed=False)

                        # Catch the only broadcast command we will accept: emergency stop
                        if write_address == 0:
                            if write_offset == MB_MAP['MB_ESTOP']:
                                estop_all_boards(modbus)
                                valid_msg_received = True
                            else:
                                modbus.logger.warning("Invalid broadcast message received")
                        else:
                            # Catch potentially damaging speed commands
                            # TODO: need to deal with 2s complement for -ve speeds
                            #if write_offset == MB_MAP['MB_MOTOR_SETPOINT']:
                            #    if write_value > MAX_MOTOR_SPEED:
                            #        modbus.logger.warning("Motor speed capped at " + str(MAX_MOTOR_SPEED) + "%")
                            #        write_value = MAX_MOTOR_SPEED

                            modbus.write_queue[write_address].append((write_offset, write_value))
                            valid_msg_received = True

        except BlockingIOError:
            # This exception means no packets are ready, we can exit the loop
            break

    return valid_msg_received


def flush_write_queue(modbus, output_socket):
    """Send out any writes waiting in the queue, ignoring those which have been superseded by a more recent message"""

    for write_address in ENABLED_BOARDS:
        # Keep trace of writes to each offset at this address
        written_offsets = []

        num_regs_to_write = len(modbus.write_queue[write_address])

        if num_regs_to_write != 0:
            modbus.logger.info("Writing " + str(num_regs_to_write) +
                                " registers to address " + str(write_address))

        while len(modbus.write_queue[write_address]) != 0:
            # Start at the end of the queue
            (write_offset, write_value) = modbus.write_queue[write_address].pop()

            # Check if this is an old (expired) message, ignore if superseded
            if write_offset not in written_offsets:
                written_offsets.append(write_offset)

                # Don't bother sending if reg already contained this value on last read
                # Disable during testing to force writes
                if True: # write_value != modbus.shadow_map[write_address][write_offset]:
                    response = modbus.write_reg(write_address, write_offset, write_value)

                    modbus.logger.info("Write reg: addr = " + str(write_address) +
                                        "  offset = " + str(write_offset) +
                                        "  value = " + str(write_value))
                    modbus.logger.info("Write response: " + str(response))

                    # Send a response to output UDP socket for each reg separately
                    if (response != None):
                        # Packet is address (2 bytes), response_offset (2 bytes), response_value (2 bytes)
                        (response_offset, response_value) = response
                        output_packet = [write_address, response_offset, response_value]
                    else:
                        # Modbus error occurred
                        # Error packets use 10000 register block
                        #  - write_address (2 bytes)
                        #  - 10002 (2 bytes)
                        #  - write_offset (2 bytes)
                        output_packet = [write_address, 10002, write_offset]

                    # Convert to bytes
                    output_packet = [entry.to_bytes(2, byteorder='little') for entry in output_packet]

                    # Flatten to byte string, ship out
                    output_socket.sendto(b"".join(output_packet), (IP_ADDRESS, OUTPUT_UDP_PORT))

    modbus.clear_write_queue()




def main():
    """Main loop"""

    output_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet, UDP

    input_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet, UDP
    input_sock.bind((IP_ADDRESS, INPUT_UDP_PORT))
    input_sock.setblocking(False)

    uki = UkiModbus(SERIAL_PORT, BAUD_RATE, TIMEOUT, MAX_RETRIES, INTER_FRAME_DELAY)

    incoming_msg_received = False  # Don't activate heartbeat timeout until one message received

    uki.logger.info("UkiModbusManager monitoring addresses " + str(ENABLED_BOARDS))

    try:
        while True:
            for full_read_address in ENABLED_BOARDS:

                # Round robin through all modbus connected boards
                beginRobinTime = time.time()
                for address in ENABLED_BOARDS:

                    # Check for incoming messages, cue up writes
                    if process_incoming_packet(uki, input_sock):
                        last_incoming_msg_time = time.time()
                        incoming_msg_received = True

                    # Check for heartbeat timeout for incoming UDP messages
                    if incoming_msg_received and (time.time() - last_incoming_msg_time) > INCOMING_MSG_HEARTBEAT_TIMEOUT:
                        estop_all_boards(uki)

                    # High priority reads, do every time
                    query_and_forward(uki, output_sock, address, MB_MAP['MB_ESTOP_STATE'], MB_MAP['MB_OUTWARD_ENDSTOP_STATE'])

                    # Lower priority reads, do one board per loop
                    if address == full_read_address:
                        uki.logger.info("Full read " + str(address))
                        query_and_forward(uki, output_sock, address, MB_MAP['MB_BRIDGE_CURRENT'], MB_MAP['MB_BOARD_TEMPERATURE'])
                        query_and_forward(uki, output_sock, address, MB_MAP['MB_MOTOR_SETPOINT'], MB_MAP['MB_CURRENT_LIMIT_OUTWARD'])
                        query_and_forward(uki, output_sock, address, MB_MAP['MB_INWARD_ENDSTOP_COUNT'], MB_MAP['MB_HEARTBEAT_EXPIRIES'])

                uki.logger.info("Completed round robin in " + str(time.time() - beginRobinTime) + " seconds")

                # TODO: Check whether to write config regs, add to write queue

                flush_write_queue(uki, output_sock)

    except KeyboardInterrupt:
        # Clean up
        output_sock.close()
        input_sock.close()
        uki.logger.info("Exiting")
        sys.exit(0)



if __name__ == "__main__":
    main()
