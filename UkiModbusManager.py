#!/usr/bin/env python
# -*- coding: utf_8 -*-
"""
 UkiModbusManager v0.2

 Chris Mock, 2017

 Provides a UDP interface to Scarab/Huhu boards.  Designed to have continuous UDP messages coming in
 to write registers, so comms errors tend to ride through as the write is retried the next time around the loop.
 Would be fairly trivial to rework such that the board modbus regs are synched with the local shadow regs, but
 a more resilient input protocol should be used (ie. not UDP)

 Licensed under GNU General Public License v3.0, https://www.gnu.org/licenses/gpl-3.0.txt

"""

#### Still to do: ####
# Read more settings from yaml config file (baud rate, UDP ports etc.)
# Allow boards to be enabled/disabled on the fly
# Deal with left/right better, inherit UkiModbus and override read/write etc.?


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

import yaml

from ModbusMap import MB_MAP

##### Defines #####
LOG_LEVEL = logging.INFO

IP_ADDRESS = "127.0.0.1"
INPUT_UDP_PORT = 9000
OUTPUT_UDP_PORT = 10001

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

DEFAULT_CONFIG_FILENAME = 'UkiConfig.json'
DEFAULT_LEFT_SERIAL_PORT = 'COM4'   # Set to None to disable
DEFAULT_RIGHT_SERIAL_PORT = 'COM9'  # Set to None to disable
# DEFAULT_SERIAL_PORT = '/dev/tty.usbserial-FTYSCI9K'
# DEFAULT_SERIAL_PORT = '/dev/tty.usbserial-FTZ5B0HX'

SEND_EVERY_WRITE = False  # Debug mode to send a write every loop, regardless of whether reg already holds that value

MAX_MOTOR_SPEED = 60  # max allowable motor speed %


class UkiModbus:

    def __init__(self, serial_port, baud_rate, timeout, max_retries, interframe_delay, enabled_boards):
        self.logger = modbus_tk.utils.create_logger("console", level=LOG_LEVEL)

        self.retries = max_retries
        self.interframe_delay = interframe_delay
        self.enabled_boards = enabled_boards

        # Shadow modbus map, store values when read, use this to check if a write needs to be made
        self.shadow_map = dict([(address, collections.defaultdict(list)) for address in self.enabled_boards])

        self.clear_write_queue()  # Initialises empty write queue

        if serial_port is None:
            self.logger.error ("Serial port disabled")
            self.enabled = False
        else:
            self.enabled = True
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
        self.write_queue = dict([(address, list()) for address in self.enabled_boards])

    def access_regs(self, command, address, start_offset, end_offset, write_data = 0):
        """Read multiple holding regs (inclusive), write single holding reg"""
        response = None

        if self.enabled == True:
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



class UkiModbusManager:
    def __init__(self, left_serial_port, right_serial_port, baud_rate, timeout, max_retries, interframe_delay,
                 input_socket, output_socket,
                 config_filename):
        self.input_socket = input_socket
        self.output_socket = output_socket
        self.config_filename = config_filename
        self.board_config = {'actuators': []}
        self.read_board_config_file()
        self.enabled_boards = []
        left_boards = []
        right_boards = []
        for actuator in self.board_config['actuators']:
            if actuator['enabled']:
                self.enabled_boards.append(actuator['address'])
                if actuator['port'] == "Left":
                    left_boards.append(actuator['address'])
                elif actuator['port'] == "Right":
                    right_boards.append(actuator['address'])

        self.uki_ports = {'left': UkiModbus(left_serial_port, baud_rate, timeout, max_retries, interframe_delay, left_boards),
                          'right': UkiModbus(right_serial_port, baud_rate, timeout, max_retries, interframe_delay, right_boards)}

        self.logger = self.uki_ports['left'].logger  # hijack left-side logger

    def read_board_config_file(self):
        """Read in YAML config file"""
        try:
            self.board_config = yaml.safe_load(open(self.config_filename, 'r', encoding='utf8'))
        except FileNotFoundError:
            self.logger.error("Config file not found: " + self.config_filename)
        except yaml.parser.ParserError as exc:
            self.logger.error("Failed to parse yaml config file:")
            self.logger.warning(exc)

    def get_port_for_address(self, address):
        board_details = list(filter(lambda board: board['address'] == address, self.board_config['actuators']))[0]  # Assume only one
        if board_details['port'] == "Left":
            port = self.uki_ports['left']
        elif board_details['port'] == "Right":
            port = self.uki_ports['right']
        else:
            port = None
        return port

    def query_and_forward(self, address, start_offset, end_offset):
        """Read modbus reg(s), send to output socket"""
        self.logger.debug("Reading from address " + str(address) + ", from offset " + str(start_offset) + " to " + str(end_offset))

        regs = self.get_port_for_address(address).read_regs(address, start_offset, end_offset)

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
                self.get_port_for_address(address).shadow_map[address][start_offset + pos] = regs[pos]
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
                self.get_port_for_address(address).shadow_map[address][offset] = None

        # Convert to bytes
        packet = [entry.to_bytes(2, byteorder='little') for entry in packet]
        #self.logger.info(len(packet))
        # Flatten to byte string, ship out
        self.output_socket.sendto(b"".join(packet), (IP_ADDRESS, OUTPUT_UDP_PORT))

    def estop_all_boards(self):
        """Queue an estop command to all boards"""
        self.logger.warning("Sending e-stop to all boards")
        for estop_address in self.enabled_boards:
            self.get_port_for_address(estop_address).write_queue[estop_address].append((MB_MAP['MB_ESTOP'], 1))

    def process_incoming_packet(self):
        """Check for incoming UDP packets, parse and store contents in write queue"""

        valid_msg_received = False

        while True:
            try:
                (incoming_packet, input_address) = self.input_socket.recvfrom(65535)

                self.logger.debug("Received" + str(len(incoming_packet)) + "bytes via UDP")

                if ((len(incoming_packet) % 2) != 0):
                    self.logger.error("Received incorrectly formatted UDP packet", str(incoming_packet))
                    # No UDP response for malformed packets
                else:
                    self.logger.debug(incoming_packet)

                    # Extract write address (first two bytes)
                    write_address = int.from_bytes(incoming_packet[0:2], byteorder='little', signed=False)

                    if write_address not in self.enabled_boards + [0]:
                        self.logger.warning("Received message for board that is not enabled: " + str(write_address))
                    else:
                        # Step through the rest of the packet four bytes at a time (ie. break down into offset/value pairs)
                        for pos in range(2, len(incoming_packet), 4):
                            write_offset = int.from_bytes(incoming_packet[pos:(pos + 2)], byteorder='little', signed=False)
                            write_value = int.from_bytes(incoming_packet[(pos + 2):(pos + 4)], byteorder='little',
                                                         signed=True)
                            #write_value_signed = int.from_bytes(incoming_packet[(pos + 2):(pos + 4)], byteorder='little',
                            #                             signed=True)

                            # Catch the only broadcast command we will accept: emergency stop
                            if write_address == 0:
                                if write_offset == MB_MAP['MB_ESTOP']:
                                    self.estop_all_boards(self)
                                    valid_msg_received = True
                                else:
                                    self.logger.warning("Invalid broadcast message received")
                            else:
                                # Catch potentially damaging speed commands
                                if write_offset == MB_MAP['MB_MOTOR_SETPOINT']:
                                    if write_value > MAX_MOTOR_SPEED:
                                        self.logger.warning("Motor speed capped at " + str(MAX_MOTOR_SPEED) + "%")
                                        write_value = MAX_MOTOR_SPEED
                                    elif write_value < -MAX_MOTOR_SPEED:
                                        self.logger.warning("Motor speed capped at " + str(-MAX_MOTOR_SPEED) + "%")
                                        write_value = -MAX_MOTOR_SPEED

                                self.get_port_for_address(write_address).write_queue[write_address].append((write_offset, write_value))
                                valid_msg_received = True

            except BlockingIOError:
                # This exception means no packets are ready, we can exit the loop
                break

        return valid_msg_received


    def flush_write_queue(self):
        """Send out any writes waiting in the queue, ignoring those which have been superseded by a more recent message"""

        for write_address in self.enabled_boards:
            # Keep trace of writes to each offset at this address
            written_offsets = []

            num_regs_to_write = len(self.get_port_for_address(write_address).write_queue[write_address])

            if num_regs_to_write != 0:
                self.logger.debug("Writing up to " + str(num_regs_to_write) +
                                    " registers to address " + str(write_address))

            while len(self.get_port_for_address(write_address).write_queue[write_address]) != 0:
                # Start at the end of the queue
                (write_offset, write_value) = self.get_port_for_address(write_address).write_queue[write_address].pop()

                # Check if this is an old (expired) message, ignore if superseded
                if write_offset not in written_offsets:
                    written_offsets.append(write_offset)

                    # Don't bother sending if reg already contained this value on last read
                    if SEND_EVERY_WRITE or write_value != self.get_port_for_address(write_address).shadow_map[write_address][write_offset]:
                        response = self.get_port_for_address(write_address).write_reg(write_address, write_offset, write_value)

                        self.logger.info("Write reg: addr = " + str(write_address) +
                                            "  offset = " + str(write_offset) +
                                            "  value = " + str(write_value))
                        self.logger.info("Write response: " + str(response))

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
                            self.get_port_for_address(write_address).shadow_map[write_address][write_offset] = None

                        # Convert to bytes
                        output_packet = [entry.to_bytes(2, byteorder='little') for entry in output_packet]

                        # Flatten to byte string, ship out
                        self.output_socket.sendto(b"".join(output_packet), (IP_ADDRESS, OUTPUT_UDP_PORT))

        self.uki_ports['left'].clear_write_queue()
        self.uki_ports['right'].clear_write_queue()

    def check_and_write_config_reg(self, address, offset, desired_value):
        """Static function to check a reg is set to a desired value, queues write if not"""
        if self.get_port_for_address(address).shadow_map[address][offset] != desired_value:
            self.get_port_for_address(address).write_queue[address].append((offset, desired_value))
            self.logger.info("Updating config reg for address " + str(address) +
                             " offset " + str(offset) + " = " + str(desired_value))

    def update_board_config(self, address):
        """
        Ensure that a board is set up as per the config file
         - Note the regs set in the config file must also be read during the full read cycle so validation can occur
         - Allows boards to be reset during operation, config is updated on first full read
        """
        # Locate config for this board
        board_config = {}
        for cfg in self.board_config['actuators']:
            if cfg['address'] == address:
                board_config = cfg

        # Update regs as needed
        self.check_and_write_config_reg(address, MB_MAP['MB_CURRENT_LIMIT_INWARD'], board_config['inwardCurrentLimit'])
        self.check_and_write_config_reg(address, MB_MAP['MB_CURRENT_LIMIT_OUTWARD'], board_config['outwardCurrentLimit'])
        self.check_and_write_config_reg(address, MB_MAP['MB_MOTOR_ACCEL'], board_config['acceleration'])


def main():
    """Main loop"""

    # Parse command line args (python3 UkiModbusManager <config file name> <serial port>)
    cmd_line_arg_count = len(sys.argv)
    config_file_name = sys.argv[1] if cmd_line_arg_count > 1 else DEFAULT_CONFIG_FILENAME
    left_serial_port = sys.argv[2] if cmd_line_arg_count > 2 else DEFAULT_LEFT_SERIAL_PORT
    right_serial_port = sys.argv[3] if cmd_line_arg_count > 3 else DEFAULT_RIGHT_SERIAL_PORT

    output_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet, UDP

    input_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet, UDP
    input_sock.bind((IP_ADDRESS, INPUT_UDP_PORT))
    input_sock.setblocking(False)

    uki = UkiModbusManager(left_serial_port, right_serial_port, BAUD_RATE, TIMEOUT, MAX_RETRIES, INTER_FRAME_DELAY,
                           input_sock, output_sock, config_file_name)

    incoming_msg_received = False  # Don't activate heartbeat timeout until one message received

    uki.logger.info("UkiModbusManager monitoring addresses " + str(uki.enabled_boards))

    try:
        while True:
            # Reread config file each full round robin in case it has been edited
            uki.read_board_config_file()

            for full_read_address in uki.enabled_boards:

                # Round robin through all modbus connected boards
                begin_robin_time = time.time()
                for address in uki.enabled_boards:

                    # Check for incoming messages, cue up writes
                    if uki.process_incoming_packet():
                        last_incoming_msg_time = time.time()
                        incoming_msg_received = True

                    # Check for heartbeat timeout for incoming UDP messages
                    if incoming_msg_received and (time.time() - last_incoming_msg_time) > INCOMING_MSG_HEARTBEAT_TIMEOUT:
                        uki.estop_all_boards()

                    # High priority reads, do every time
                    uki.query_and_forward(address, MB_MAP['MB_ESTOP_STATE'], MB_MAP['MB_OUTWARD_ENDSTOP_STATE'])

                    # Lower priority reads, do one board per loop
                    if address == full_read_address:
                        uki.logger.debug("Full read " + str(address))
                        uki.query_and_forward(address, MB_MAP['MB_BRIDGE_CURRENT'], MB_MAP['MB_BOARD_TEMPERATURE'])
                        uki.query_and_forward(address, MB_MAP['MB_MOTOR_SETPOINT'], MB_MAP['MB_CURRENT_LIMIT_OUTWARD'])
                        uki.query_and_forward(address, MB_MAP['MB_INWARD_ENDSTOP_COUNT'], MB_MAP['MB_HEARTBEAT_EXPIRIES'])
                        uki.update_board_config(address)

                uki.logger.info("Completed round robin in " + str(time.time() - begin_robin_time) + " seconds")

                uki.flush_write_queue()

    except KeyboardInterrupt:
        # Clean up
        output_sock.close()
        input_sock.close()
        uki.logger.info("Exiting")
        sys.exit(0)



if __name__ == "__main__":
    main()
