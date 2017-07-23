#!/usr/bin/env python
# -*- coding: utf_8 -*-
"""
 Uki Articulation

 Chris Mock, 2017

 Uki Articulation UI
  - Controls UkiModbusManager
  - Plays CSV scripts/sequences to control speed/accel

 Licensed under GNU General Public License v3.0, https://www.gnu.org/licenses/gpl-3.0.txt

"""

import threading
import time
import logging
import UkiModbusManager as uki
import UkiLogger
from UkiGUI import *
import yaml
import csv
from ModbusMap import MB_MAP

LOG_LEVEL = logging.INFO

RESET_LOOPS = 3  # Number of times to reset boards prior to running script

# rework player piano to states, not 'playing'
# stop script if any current limit detected
# error handling: queue full, invalid config input
# heartbeat
# test speed cap
# instead of self.playing start/stop player thread? messy as-is
# move player piano into separate file
# multiple logger queues
# set log level on the fly

# stop script (just use stop all button)
# legs in (use script)
# wings down (use script)


class ThreadManager:
    def __init__(self, master):
        self.testing = 0

        self.master = master

        # Thread control vars (boolean reads are atomic)
        self.running = True
        self.playing = False
        self.fault_active = False
        self.gui_config = {}  # Shadow GUI config, updated by Uki MM thread
        self.gui_config_lock = threading.Lock()  # Lock for self.gui_config

        # Setup threads and queues
        self.gui_queue = queue.Queue()            # Log messages to GUI
        self.uki_mm_thread_queue = queue.Queue()  # Control messages from GUI to UkiModbusManager thread
        self.uki_mm_thread = threading.Thread(target=self.uki_mm_control)
        self.uki_mm_comms_queue = queue.Queue()   # Data to send out to boards from Player Piano thread
        self.uki_mm_comms_thread = threading.Thread(target=self.uki_player_piano)
        self.uki_mm_responses_queue = queue.Queue()  # Queue to hold responses (reads) coming in from boards

        self.gui = UkiGUI(master, self.gui_queue, self.uki_mm_thread_queue)
        self.periodic_gui_update()

        self.logger = UkiLogger.get_logger(log_level=LOG_LEVEL, queue=self.gui_queue)

        self.uki_mm_thread.start()
        self.uki_mm_comms_thread.start()

    def start_uki_modbus_manager(self, config):
        left_port = config['left_comm_port'] if config['left_comm_disabled'] == 0 else None
        right_port = config['right_comm_port'] if config['right_comm_disabled'] == 0 else None

        return uki.UkiModbusManager(left_serial_port=left_port, right_serial_port=right_port,
                                    config_filename=config['config_file'],
                                    logger=self.logger,
                                    incoming_queue=self.uki_mm_comms_queue,
                                    outgoing_queue=self.uki_mm_responses_queue)

    def uki_mm_control(self):
        # UkiMM checks queue for quit signal, input settings, script triggers etc.
        uki_mm_started = False
        uki_manager = None
        estopped_boards = {}

        while self.running:
            if uki_mm_started:
                uki_manager.main_poll_loop()

            # Check for messages from GUI to wrapper
            while self.uki_mm_thread_queue.qsize():
                try:
                    queue_obj = self.uki_mm_thread_queue.get(0)
                    gui_config = queue_obj['config']
                    with self.gui_config_lock:
                        self.gui_config = gui_config  # Export for other threads to use
                    msg = queue_obj['message']

                    if not uki_mm_started:
                        # Only start Uki MM once we have config data from the GUI
                        uki_manager = self.start_uki_modbus_manager(gui_config)
                        uki_mm_started = True

                    if msg == 'QUIT':
                        self.logger.warning('Quitting...')
                        uki_manager.estop_all_boards()
                        self.running = False
                    elif msg == 'RESTART':
                        self.logger.warning('Restarting UkiModbusManager')
                        uki_manager.cleanup()
                        uki_manager = self.start_uki_modbus_manager(gui_config)
                    elif msg == 'UDP':
                        uki_manager.udp_input(True)
                    elif msg in ('CSV', 'None'):
                        uki_manager.udp_input(False)
                    elif msg == 'STOP':
                        uki_manager.estop_all_boards()
                        self.playing = False
                    elif msg == 'RESET':
                        uki_manager.reset_all_boards()
                    elif msg == 'PLAY':
                        self.playing = True

                except queue.Empty:
                    pass

            # Check for messages coming in from boards eg. EStop state
            while self.uki_mm_responses_queue.qsize():
                try:
                    response = self.uki_mm_responses_queue.get(0)
                    # First byte is address
                    address = response[0]
                    # Offset/value pairs follow
                    for response_index in range(1, len(response), 2):
                        offset = response[response_index]
                        value = response[response_index + 1]
                        if offset == MB_MAP['MB_ESTOP_STATE']:
                            estopped_boards[address] = value

                except queue.Empty:
                    pass

            # Check whether any boards have estopped
            estop_active = False
            for board_address, board_estop_state in estopped_boards.items():
                if board_estop_state:
                    estop_active = True
            self.fault_active = estop_active  # Transfer once value determined to keep atomic behaviour
            if estop_active:
                self.logger.warning("EStop detected: " + str(estopped_boards))

        uki_manager.cleanup()

    def uki_send_comms(self, address, offset, value):
        if self.playing:
            self.logger.info('Add ' + str(address) + '  offset ' + str(offset) + '=' + str(value))
            self.uki_mm_comms_queue.put((address, offset, value))

    def uki_player_piano(self):
        #piano_states = {'IDLE': 0, 'INIT': 1, 'RESET_ESTOP': 2, 'ROLLING': 3, 'STOPPING': 4}
        #piano_state = piano_states['IDLE']
        loops = 0

        while self.running:
            board_names = []
            board_mapping = {}
            current_speed = {}
            current_accel = {}
            if self.playing:
                # Fetch gui config (locked)
                with self.gui_config_lock:
                    csv_filename = self.gui_config['script_file']
                    loops = self.gui_config['script_loops']
                    frame_period = self.gui_config['script_rate']
                    config_file = self.gui_config['config_file']

                # Read YAML config file, map names to addresses
                board_names = []
                board_mapping = {}
                current_speed = {}
                current_accel = {}
                try:
                    board_config = yaml.safe_load(open(config_file, 'r', encoding='utf8'))

                    for cfg in board_config['actuators']:
                        board_names.append(cfg['name'])
                        board_mapping[cfg['name']] = cfg['address']
                        current_speed[cfg['name']] = 0
                        current_accel[cfg['name']] = 100
                except FileNotFoundError:
                    self.logger.error('Config file not found: ' + config_file)
                    self.playing = False
                except yaml.parser.ParserError as exc:
                    self.logger.error('Failed to parse yaml config file ' + config_file + ': ' + str(exc))
                    self.playing = False

            # Reset estop
            if self.playing:
                # Reset a few times just in case of downstream errors
                for reset_loops in range(0, RESET_LOOPS):
                    self.logger.info("Resetting all boards: " + str(reset_loops + 1) + " of " + str(RESET_LOOPS))
                    for board in board_names:
                        self.uki_send_comms(address=board_mapping[board],
                                            offset=MB_MAP['MB_RESET_ESTOP'],
                                            value=0x5050)
                    time.sleep(2)  # Wait for reset messages to go out
            else:
                time.sleep(0.1)  # Slow poll loop until we start again

            for loop_count in range(0, loops):
                if not self.playing:
                    break

                self.logger.info('Starting loop ' + str(loop_count + 1) + ' of ' + str(loops) + ': ' + csv_filename)

                with open(csv_filename, newline='') as csv_file:
                    csv_reader = csv.reader(csv_file, delimiter=',', quotechar='"')

                    # Read header row
                    header = next(csv_reader)
                    try:
                        actuator_names_by_col = [cell.split('_')[0] for cell in header]
                        speed_accel = [cell.split('_')[1] for cell in header]
                    except IndexError:
                        self.logger.error('Each CSV column heading must have one underscore eg. LeftRearHip_Speed')
                        self.playing = False

                    # Loop over each remaining row in CSV
                    frame_number = 1
                    for row in csv_reader:
                        if not self.playing:
                            break

                        self.logger.debug('Frame ' + str(frame_number) + ' (row ' + str(frame_number + 1) + ')')
                        frame_number += 1

                        # Check for invalid row, too long/short

                        # Loop over each cell in the row, process non-blank entries
                        for cell_index in range(0, len(row)):
                            if row[cell_index] != '':
                                if speed_accel[cell_index] == 'Speed':
                                    self.logger.info(actuator_names_by_col[cell_index] + ' speed set to ' + row[cell_index])
                                    current_speed[actuator_names_by_col[cell_index]] = int(row[cell_index])
                                elif speed_accel[cell_index] == 'Accel':
                                    self.logger.info(actuator_names_by_col[cell_index] + ' accel set to ' + row[cell_index])
                                    current_accel[actuator_names_by_col[cell_index]] = int(row[cell_index])
                                else:
                                    self.logger.warning('Invalid column name, does not contain "_Speed" or "_Accel"' +
                                                        header[cell_index])
                                    # Don't exit, need to fall thru to force stop

                        for board in board_names:
                            # Range check inputs, warn?

                            # Just for now always update every board, every frame
                            self.uki_send_comms(address=board_mapping[board],
                                                offset=MB_MAP['MB_MOTOR_SETPOINT'],
                                                value=current_speed[board])

                            self.uki_send_comms(address=board_mapping[board],
                                                offset=MB_MAP['MB_MOTOR_ACCEL'],
                                                value=current_accel[board])

                        time.sleep(frame_period)

            # Send final stop command to finish script
            for board in board_names:
                self.uki_send_comms(address=board_mapping[board],
                                    offset=MB_MAP['MB_MOTOR_SETPOINT'],
                                    value=0)
                self.uki_send_comms(address=board_mapping[board],
                                    offset=MB_MAP['MB_MOTOR_ACCEL'],
                                    value=100)

            #if self.playing:
                self.playing = False
                self.logger.info("Script finished")

    def periodic_gui_update(self):
        self.gui.process_queue()
        self.master.after(100, self.periodic_gui_update)   # Update GUI with wrapper info every 100ms


if __name__ == "__main__":
    root = Tk()
    gui = ThreadManager(root)
    root.mainloop()