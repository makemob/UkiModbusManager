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

INITIAL_LOG_LEVEL = logging.INFO
LOG_LEVEL_MAP = {'ERROR': logging.ERROR,
                 'WARNING': logging.WARN,
                 'INFO': logging.INFO,
                 'DEBUG': logging.DEBUG}

RESET_LOOPS = 3  # Number of times to reset boards prior to running script
THREAD_DELAY = 0.1  # Seconds to delay when avoiding thread spinning.  Sets GUI update rate

# Still to do:
# - build windows executable
# - error handling: queues full, invalid config input
# - thread interlocking, one exception should quit all
# - move player piano into separate file
# - small memory leak somewhere..

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

        self.log_level = INITIAL_LOG_LEVEL
        self.logger = UkiLogger.get_logger(log_level=self.log_level, queue=self.gui_queue)

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

                    if LOG_LEVEL_MAP[gui_config['log_level']] != self.log_level:
                        self.log_level = LOG_LEVEL_MAP[gui_config['log_level']]
                        self.logger.warning("Log level changed to " + gui_config['log_level'])
                        self.logger.setLevel(LOG_LEVEL_MAP[gui_config['log_level']])

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
                        udpEnabled = uki_manager.udp_input_enabled
                        uki_manager.cleanup()
                        time.sleep(5)      # Short delay to allow comms drivers to become available on Windows systems
                        uki_manager = self.start_uki_modbus_manager(gui_config)
                        uki_manager.udp_input(udpEnabled)
                    elif msg == 'UDP':
                        uki_manager.udp_input(True)
                        uki_manager.set_accel_config(True)      # Allow config file to set accel
                    elif msg in ('CSV', 'None'):
                        uki_manager.udp_input(False)
                        uki_manager.set_accel_config(False)  # Script will set accel values
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
            last_estopped_boards = estopped_boards.copy()
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
            self.fault_active = estop_active  # Transfer only once value determined, can't glitch through False
            if estop_active and last_estopped_boards != estopped_boards:
                self.logger.warning("EStop detected: " + ','.join([str(key) for key in estopped_boards]))

        uki_manager.cleanup()

    def uki_send_comms(self, address, offset, value):
        if self.playing:
            self.logger.debug('Address ' + str(address) + ', offset ' + str(offset) + '=' + str(value))
            self.uki_mm_comms_queue.put((address, offset, value))

    def uki_player_piano(self):
        # Reads from CSV script containing speed (%), accel (%) or position (mm) targets

        piano_states = {'IDLE': 0, 'INIT': 1, 'RESET_ESTOP': 2, 'ROLLING': 3, 'STOPPING': 4}
        piano_state = piano_states['IDLE']

        while self.running:
            if piano_state == piano_states['IDLE']:
                if self.playing:
                    piano_state = piano_states['INIT']
                else:
                    time.sleep(THREAD_DELAY)  # Slow poll loop until we start again

            elif piano_state == piano_states['INIT']:
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
                current_position = {}
                position_control_boards = []
                try:
                    board_config = yaml.safe_load(open(config_file, 'r', encoding='utf8'))

                    for cfg in board_config['actuators']:
                        if cfg['enabled']:
                            board_names.append(cfg['name'])
                            board_mapping[cfg['name']] = cfg['address']
                            current_speed[cfg['name']] = 0
                            current_accel[cfg['name']] = 100
                            current_position[cfg['name']] = None
                except FileNotFoundError:
                    self.logger.error('Config file not found: ' + config_file)
                    self.playing = False
                except yaml.parser.ParserError as exc:
                    self.logger.error('Failed to parse yaml config file ' + config_file + ': ' + str(exc))
                    self.playing = False

                if self.playing:
                    piano_state = piano_states['RESET_ESTOP']
                else:
                    piano_state = piano_states['IDLE']

            elif piano_state == piano_states['RESET_ESTOP']:
                # Reset estop a few times just in case of downstream errors
                for reset_loops in range(0, RESET_LOOPS):
                    self.logger.warning("Resetting all boards: " + str(reset_loops + 1) + " of " + str(RESET_LOOPS) + " attempts")
                    for board in board_names:
                        self.uki_send_comms(address=board_mapping[board],
                                            offset=MB_MAP['MB_RESET_ESTOP'],
                                            value=0x5050)
                    time.sleep(2)  # Wait for reset messages to go out

                if self.playing:
                    loop_count = 0
                    piano_state = piano_states['ROLLING']
                else:
                    piano_state = piano_states['IDLE']

            elif piano_state == piano_states['ROLLING']:
                self.logger.warning('Starting loop ' + str(loop_count + 1) + ' of ' + str(loops) + ': ' + csv_filename)

                if not os.path.isfile(csv_filename):
                    self.logger.error('Script file not found:' + csv_filename)
                    self.playing = False
                else:
                    with open(csv_filename, newline='') as csv_file:
                        csv_reader = csv.reader(csv_file, delimiter=',', quotechar='"')

                        # Read header row
                        header = next(csv_reader)
                        try:
                            actuator_names_by_col = [cell.split('_')[0] for cell in header]
                            speed_accel_position = [cell.split('_')[1] for cell in header]
                        except IndexError:
                            self.logger.error('Each CSV column heading must have one underscore eg. LeftRearHip_Speed')
                            self.playing = False

                        # Determine which boards are set up for goto position control
                        for cell_index in range(0, len(header)):
                            if speed_accel_position[cell_index] == 'Position':
                                position_control_boards.append(actuator_names_by_col[cell_index])
                        if position_control_boards:
                            self.logger.info('The following boards have position control enabled: ' + str(position_control_boards))

                        # Loop over each remaining row in CSV
                        frame_number = 1
                        for row in csv_reader:
                            # Any estopped board will stop the script
                            if self.fault_active:
                                self.logger.warning("Stopping script, estop detected")
                                self.playing = False

                            if not self.playing:
                                break

                            self.logger.debug('Frame ' + str(frame_number) + ' (row ' + str(frame_number + 1) + ')')
                            frame_number += 1

                            # Check for invalid row, too long/short

                            # Loop over each cell in the row, process non-blank entries
                            for cell_index in range(0, len(row)):
                                if row[cell_index] != '':
                                    if speed_accel_position[cell_index] == 'Speed':
                                        self.logger.info(actuator_names_by_col[cell_index] + ' speed set to ' + row[cell_index])
                                        current_speed[actuator_names_by_col[cell_index]] = int(row[cell_index])
                                    elif speed_accel_position[cell_index] == 'Accel':
                                        self.logger.info(actuator_names_by_col[cell_index] + ' accel set to ' + row[cell_index])
                                        current_accel[actuator_names_by_col[cell_index]] = int(row[cell_index])
                                    elif speed_accel_position[cell_index] == 'Position':
                                        self.logger.info(actuator_names_by_col[cell_index] + ' position set to ' + row[cell_index])
                                        current_position[actuator_names_by_col[cell_index]] = int(row[cell_index])
                                    else:
                                        self.logger.warning('Invalid column name, does not contain "_Speed", "_Accel" or "_Position"' +
                                                            header[cell_index])
                                        # Don't exit, need to fall thru to force stop

                            # Send out commands to boards
                            for board in board_names:
                                # Range check inputs, warn?

                                if board in position_control_boards:
                                    # Send goto position @ speed commands for this board
                                    if current_position[board] is not None:
                                        # Only update position once per row to avoid hunting
                                        self.uki_send_comms(address=board_mapping[board],
                                                            offset=MB_MAP['MB_GOTO_POSITION'],
                                                            value=current_position[board] * 10)   # Convert mm to mm/10
                                        current_position[board] = None
                                        # The speed column for this board is now a goto speed
                                        self.uki_send_comms(address=board_mapping[board],
                                                            offset=MB_MAP['MB_GOTO_SPEED_SETPOINT'],
                                                            value=current_speed[board])
                                        # Acceleration can be left out if not wanted, but send anyway
                                        self.uki_send_comms(address=board_mapping[board],
                                                            offset=MB_MAP['MB_MOTOR_ACCEL'],
                                                            value=current_accel[board])

                                else:
                                    # Normal speed/accel mode for this board

                                    # Just for now always update every board, every frame
                                    self.uki_send_comms(address=board_mapping[board],
                                                        offset=MB_MAP['MB_MOTOR_SETPOINT'],
                                                        value=current_speed[board])

                                    self.uki_send_comms(address=board_mapping[board],
                                                        offset=MB_MAP['MB_MOTOR_ACCEL'],
                                                        value=current_accel[board])

                            time.sleep(frame_period)

                    if loop_count < (loops - 1):
                        loop_count += 1
                    else:
                        self.playing = False

                if not self.playing:
                    piano_state = piano_states['STOPPING']

            elif piano_state == piano_states['STOPPING']:
                # Send final stop command to finish script
                for board in board_names:
                    self.uki_send_comms(address=board_mapping[board],
                                        offset=MB_MAP['MB_MOTOR_SETPOINT'],
                                        value=0)
                    self.uki_send_comms(address=board_mapping[board],
                                        offset=MB_MAP['MB_MOTOR_ACCEL'],
                                        value=100)

                self.logger.info("Script finished")
                piano_state = piano_states['IDLE']

    def periodic_gui_update(self):
        self.gui.process_queue()
        self.master.after(int(THREAD_DELAY * 1000), self.periodic_gui_update)   # Update GUI with wrapper info every few ms


if __name__ == "__main__":
    root = Tk()
    gui = ThreadManager(root)
    root.mainloop()