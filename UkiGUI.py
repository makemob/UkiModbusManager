#!/usr/bin/env python
# -*- coding: utf_8 -*-
"""
 UkiModbusManager GUI

 Chris Mock, 2017

 TkInter GUI for UkiModbusManager

 Licensed under GNU General Public License v3.0, https://www.gnu.org/licenses/gpl-3.0.txt

"""

from tkinter import *
import tkinter.scrolledtext as tkst
import os
import glob
import threading
import queue
import time
import UkiModbusManager as uki
import logging
import UkiLogger

DEFAULT_CONFIG_FILE = 'UkiConfig.json'
DEFAULT_LEFT_COMM_PORT = 'COM4' # None
DEFAULT_RIGHT_COMM_PORT = 'COM9' # None

MAX_WRAPPER_LOG_ROWS = 100
LOG_LEVEL = logging.WARNING

# run scripts (player piano)
# stop script (just use stop all button)
# legs in (use script)
# wings down (use script)
# send out commands to UkiMM (stop, reset)
# error handling: queue full, invalid config input

class UkiGUI:
    def __init__(self, master, gui_queue, wrapper_queue):
        self.master = master
        self.wrapper_queue = wrapper_queue
        self.gui_queue = gui_queue

        master.title('UKI Articulation')

        self.scarab_image = PhotoImage(file='scarab.gif')
        self.label = Label(master, image=self.scarab_image)
        self.label.grid(row=0, column=0, sticky='W', rowspan=4, columnspan=2)

        # Select input source
        self.input_label = Label(master, text='Select input:')
        self.input_label.grid(row=0, column=2, sticky='W')
        self.input_sources = ['UDP', 'CSV', 'None']
        self.input_source = StringVar()
        self.input_source.set(self.input_sources[0])
        self.input_selector = {}
        row_num = 1
        for src in self.input_sources:
            self.input_selector[src] = Radiobutton(master,
                                        text=src,
                                        padx=10,
                                        variable=self.input_source,
                                        command=self.input_changed,
                                        value=src)
            self.input_selector[src].grid(row=row_num, column=2, sticky='W')
            row_num += 1

        # Control buttons
        self.close_button = Button(master, text='Quit', command=self.trigger_quit)
        self.close_button.grid(row=1, column=4)

        self.stop_button = Button(master, text='Stop All', command=self.trigger_stop)
        self.stop_button.grid(row=2, column=4)

        self.reset_button = Button(master, text='Reset All', command=self.trigger_reset)
        self.reset_button.grid(row=3, column=4)

        # Comm ports
        self.left_comm_port = StringVar()
        self.left_comm_port.set(DEFAULT_LEFT_COMM_PORT)
        self.left_comm_label = Label(master, text='Left comm port:')
        self.left_comm_label.grid(row=row_num, column=0, sticky='W')
        self.left_comm_entry = Entry(master, textvariable=self.left_comm_port)
        self.left_comm_entry.grid(row=row_num, column=1, columnspan=2, sticky='EW')
        self.left_comm_disabled = IntVar()
        self.left_comm_disable_button = Checkbutton(master, text='Disable', padx=5, variable=self.left_comm_disabled)
        self.left_comm_disable_button.grid(row=row_num, column=3, sticky='W')
        self.restart_button = Button(master, text='Restart Wrapper', command=self.trigger_restart)
        self.restart_button.grid(row=row_num, column=4, rowspan=3)
        row_num += 1
        self.right_comm_port = StringVar()
        self.right_comm_port.set(DEFAULT_RIGHT_COMM_PORT)
        self.right_comm_label = Label(master, text='Right comm port:')
        self.right_comm_label.grid(row=row_num, column=0, sticky='W')
        self.right_comm_entry = Entry(master, textvariable=self.right_comm_port)
        self.right_comm_entry.grid(row=row_num, column=1, columnspan=2, sticky='EW')
        self.right_comm_disabled = IntVar()
        self.right_comm_disable_button = Checkbutton(master, text='Disable', padx=5, variable=self.right_comm_disabled)
        self.right_comm_disable_button.grid(row=row_num, column=3, sticky='W')
        row_num += 1

        # Config file
        self.config_file = StringVar()
        self.config_file.set(DEFAULT_CONFIG_FILE)
        self.config_file_label = Label(master, text='Config file:')
        self.config_file_label.grid(row=row_num, column=0, sticky=W)
        self.config_file_entry = Entry(master, textvariable=self.config_file)
        self.config_file_entry.grid(row=row_num, column=1, columnspan=3, sticky='EW')
        row_num += 1

        # Set script directory
        self.path_label = Label(master, text='Script directory:')
        self.path_label.grid(row=row_num, column=0, sticky='W')
        self.path = StringVar()
        self.path.set(os.getcwd())
        self.path_selector = Entry(master, textvariable=self.path)
        self.path_selector.grid(row=row_num, column=1, columnspan=3, sticky='EW')
        self.refresh_button = Button(master, text='Refresh Scripts', command=self.update_filenames)
        self.refresh_button.grid(row=row_num, column=4)

        # List scripts
        self.list_label = Label(master, text='Select script:')
        self.list_label.grid(row=row_num + 1, column=0, sticky='NW')
        self.files_listbox = Listbox(master)
        self.files_listbox.grid(row=row_num + 1, column=1, columnspan=3, sticky='NSEW')
        self.update_filenames()

        self.play_button = Button(master, text='Run Script', command=self.trigger_script, state=DISABLED)
        self.play_button.grid(row=row_num + 1, column=4)

        # Wrapper debug out
        self.wrapper_label = Label(master, text='Log:')
        self.wrapper_label.grid(row=row_num + 2, column=0, sticky='W')
        self.wrapper_log = tkst.ScrolledText(master, height=15, wrap=NONE, relief=SUNKEN, bd=2)
        self.wrapper_log.grid(row=row_num + 3, column=0, columnspan=5, sticky='NSEW')

        # Only allow text boxes to expand vertically
        master.rowconfigure(row_num + 1, weight=1)
        master.rowconfigure(row_num + 3, weight=1)

        # All columns can expand
        for col in range(0, 5):
            master.columnconfigure(col, weight=1)

    def trigger_quit(self):
        self.wrapper_queue.put('QUIT')
        self.master.quit()

    def trigger_script(self):
        self.wrapper_queue.put('SCRIPT:' + "blahblah.csv")

    def trigger_stop(self):
        self.wrapper_queue.put('STOP')
        self.input_source.set('None')
        # Send state change to wrapper

    def trigger_reset(self):
        self.wrapper_queue.put('RESET')

    def trigger_restart(self):
        self.wrapper_queue.put('RESTART')

    def input_changed(self):
        self.wrapper_queue.put(self.input_source.get())
        play_state = ACTIVE if self.input_source.get() == 'CSV' else DISABLED
        self.play_button.config(state=play_state)  # grey out play button

    def update_filenames(self):
        self.script_files = glob.glob(os.path.join(self.path.get(), '*.[cC][sS][vV]'))
        self.files_listbox.delete(0, END)
        for filename in self.script_files:
            self.files_listbox.insert(END, os.path.split(filename)[1])

    def process_queue(self):
        while self.gui_queue.qsize():
            # Add incoming log messages to the GUI in scrollbox
            try:
                msg = self.gui_queue.get(0).message  # queue holds LogRecords

                # If the last line is visible, automatically scroll
                scroll_automatically = (self.wrapper_log.bbox('end-1c') is not None)

                self.wrapper_log.insert(END, msg + '\n')

                # Limit scroll history
                buffer_rows = int(self.wrapper_log.index('end').split('.')[0]) - 1
                if buffer_rows > MAX_WRAPPER_LOG_ROWS:
                    self.wrapper_log.delete('1.0', str(buffer_rows - MAX_WRAPPER_LOG_ROWS) + '.0')

                if scroll_automatically:
                    self.wrapper_log.see(END)

            except queue.Empty:
                pass


class ThreadManager:
    def __init__(self, master):
        self.testing = 0

        self.master = master

        self.running = True
        self.wrapper_queue = queue.Queue()  # Messages to wrapper
        self.gui_queue = queue.Queue()  # Messages to GUI
        self.wrapper_thread = threading.Thread(target=self.wrapper)

        self.gui = UkiGUI(master, self.gui_queue, self.wrapper_queue)

        self.periodic_gui_update()

        self.logger = UkiLogger.get_logger(log_level=LOG_LEVEL, queue=self.gui_queue)

        self.wrapper_thread.start()

    def start_uki_modbus_manager(self):
        left_port = self.gui.left_comm_port.get() if self.gui.left_comm_disabled.get() == 0 else None
        right_port = self.gui.right_comm_port.get() if self.gui.right_comm_disabled.get() == 0 else None

        return uki.UkiModbusManager(left_port, right_port, self.gui.config_file.get(), self.logger)

    def wrapper(self):

        uki_manager = self.start_uki_modbus_manager()

        while self.running:
            # UkiMM checks queue for quit signal, input settings, script triggers

            uki_manager.main_poll_loop()

            while self.wrapper_queue.qsize():

                try:
                    # Check for messages from GUI to wrapper
                    msg = self.wrapper_queue.get(0)
                    print(msg)

                    if msg == 'QUIT':
                        self.logger.warning('Quitting...')
                        self.running = False
                    elif msg == 'RESTART':
                        self.logger.warning('Restarting UkiModbusManager')
                        uki_manager.cleanup()
                        uki_manager = self.start_uki_modbus_manager()
                    elif msg == 'UDP':
                        uki_manager.udp_input(True)
                    elif msg in ('CSV', 'None'):
                        uki_manager.udp_input(False)

                except queue.Empty:
                    pass

        uki_manager.cleanup()


    def periodic_gui_update(self):
        self.gui.process_queue()
        self.master.after(100, self.periodic_gui_update)   # Update GUI with wrapper info every 100ms


if __name__ == "__main__":
    root = Tk()
    gui = ThreadManager(root)
    root.mainloop()


