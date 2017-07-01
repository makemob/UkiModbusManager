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
import queue
import time
import logging
from tkinter import *
import UkiModbusManager as uki
import UkiLogger
from UkiGUI import *

LOG_LEVEL = logging.INFO

# set up queue to ship out messages to wrapper
# main poll loop needs to run in steps
# run scripts (player piano)
# stop script (just use stop all button)
# legs in (use script)
# wings down (use script)
# error handling: queue full, invalid config input
# script loops
# heartbeat
# test speed cap
# move threadmanager to UkiArticulation


class ThreadManager:
    def __init__(self, master):
        self.testing = 0

        self.master = master

        self.running = True
        self.gui_queue = queue.Queue()            # Log messages to GUI
        self.uki_mm_thread_queue = queue.Queue()  # Control messages to UkiModbusManager thread
        self.uki_mm_thread = threading.Thread(target=self.uki_mm_control)
        self.uki_mm_comms_queue = queue.Queue()   # Data to send out to boards
        self.uki_mm_comms_thread = threading.Thread(target=self.uki_player_piano)

        self.gui = UkiGUI(master, self.gui_queue, self.uki_mm_thread_queue)

        self.periodic_gui_update()

        self.logger = UkiLogger.get_logger(log_level=LOG_LEVEL, queue=self.gui_queue)

        self.uki_mm_thread.start()
        self.uki_mm_comms_thread.start()

    def start_uki_modbus_manager(self):
        left_port = self.gui.left_comm_port.get() if self.gui.left_comm_disabled.get() == 0 else None
        right_port = self.gui.right_comm_port.get() if self.gui.right_comm_disabled.get() == 0 else None

        return uki.UkiModbusManager(left_serial_port=left_port, right_serial_port=right_port,
                                    config_filename=self.gui.config_file.get(),
                                    logger=self.logger, incoming_queue=self.uki_mm_comms_queue)

    def uki_mm_control(self):

        uki_manager = self.start_uki_modbus_manager()

        while self.running:
            # UkiMM checks queue for quit signal, input settings, script triggers

            uki_manager.main_poll_loop()

            while self.uki_mm_thread_queue.qsize():
                try:
                    # Check for messages from GUI to wrapper
                    msg = self.uki_mm_thread_queue.get(0)
                    print(msg)

                    if msg == 'QUIT':
                        self.logger.warning('Quitting...')
                        uki_manager.estop_all_boards()
                        self.running = False
                    elif msg == 'RESTART':
                        self.logger.warning('Restarting UkiModbusManager')
                        uki_manager.cleanup()
                        uki_manager = self.start_uki_modbus_manager()
                    elif msg == 'UDP':
                        uki_manager.udp_input(True)
                    elif msg in ('CSV', 'None'):
                        uki_manager.udp_input(False)
                    elif msg == 'STOP':
                        uki_manager.estop_all_boards()
                    elif msg == 'RESET':
                        uki_manager.reset_all_boards()

                except queue.Empty:
                    pass

        uki_manager.cleanup()

    def uki_player_piano(self):
        while self.running:
            if self.gui.input_source.get() == 'CSV':
                self.logger.info("Run 30")
                self.uki_mm_comms_queue.put((24, 200, 30))
                time.sleep(3)
                self.uki_mm_comms_queue.put((24, 200, -30))
            time.sleep(3)


    def periodic_gui_update(self):
        self.gui.process_queue()
        self.master.after(100, self.periodic_gui_update)   # Update GUI with wrapper info every 100ms


if __name__ == "__main__":
    root = Tk()
    gui = ThreadManager(root)
    root.mainloop()