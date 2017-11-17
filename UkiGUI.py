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
import queue

DEFAULT_CONFIG_FILE = 'UkiConfig.json'
#DEFAULT_CONFIG_FILE = 'BenchtestConfig.json'
DEFAULT_LEFT_COMM_PORT = 'COM5' # None
#DEFAULT_LEFT_COMM_PORT = '/dev/tty.usbserial-A101OCIF'
DEFAULT_RIGHT_COMM_PORT = 'COM4' # None

DEFAULT_LOG_LEVEL = 'INFO'

DEFAULT_PIANO_LOOPS = 1
DEFAULT_PIANO_RATE = 0.5  # seconds

MAX_WRAPPER_LOG_ROWS = 1000

class UkiGUI:
    def __init__(self, master, gui_queue, uki_mm_thread_queue):
        self.master = master
        self.uki_mm_thread_queue = uki_mm_thread_queue
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
        row_num += 1

        # Set loop count
        self.piano_loops = IntVar()
        self.piano_loops.set(DEFAULT_PIANO_LOOPS)
        self.piano_loops_label = Label(master, text='Script loops:')
        self.piano_loops_label.grid(row=row_num, column=0, sticky=W)
        self.piano_loops_entry = Entry(master, textvariable=self.piano_loops)
        self.piano_loops_entry.grid(row=row_num, column=1, columnspan=3, sticky='EW')
        row_num += 1

        # Set script rate
        self.piano_rate = DoubleVar()
        self.piano_rate.set(DEFAULT_PIANO_RATE)
        self.piano_rate_label = Label(master, text='Script rate (secs/row):')
        self.piano_rate_label.grid(row=row_num, column=0, sticky=W)
        self.piano_rate_entry = Entry(master, textvariable=self.piano_rate)
        self.piano_rate_entry.grid(row=row_num, column=1, columnspan=3, sticky='EW')
        row_num += 1

        # List scripts
        self.list_label = Label(master, text='Select script:')
        self.list_label.grid(row=row_num, column=0, sticky='NW')
        self.files_listbox = Listbox(master)
        self.files_listbox.grid(row=row_num, column=1, columnspan=3, sticky='NSEW')
        self.update_filenames()

        self.play_button = Button(master, text='Run Script', command=self.trigger_script, state=DISABLED)
        self.play_button.grid(row=row_num, column=4)
        row_num += 1

        # Set log level
        self.log_level_label = Label(master, text='Log Level:')
        self.log_level_label.grid(row=row_num, column=0, sticky='NW')
        self.log_level = StringVar()
        self.log_level.set(DEFAULT_LOG_LEVEL)
        self.log_level_option = OptionMenu(master, self.log_level, 'ERROR', 'WARNING', 'INFO', 'DEBUG')
        self.log_level_option.grid(row=row_num, column=1, columnspan=3, sticky='EW')

        # Wrapper debug out
        self.wrapper_label = Label(master, text='Log:')
        self.wrapper_label.grid(row=row_num + 1, column=0, sticky='W')
        # Must set undo to false in log window or memory usage expands unbounded..
        self.wrapper_log = tkst.ScrolledText(master, height=15, wrap=NONE, relief=SUNKEN, bd=2, undo=False)
        self.wrapper_log.grid(row=row_num + 2, column=0, columnspan=5, sticky='NSEW')

        # Only allow text boxes to expand vertically
        master.rowconfigure(row_num, weight=1)
        master.rowconfigure(row_num + 2, weight=1)

        # All columns can expand
        for col in range(0, 5):
            master.columnconfigure(col, weight=1)

    def add_to_gui_queue(self, msg = ''):
        # Build up object to place in queue from GUI to UKI MM

        # First build the config dictionary:
        # Need to protect against empty numeric values
        try:
            piano_loops = self.piano_loops.get()
        except TclError:
            piano_loops = DEFAULT_PIANO_LOOPS
        try:
            piano_rate = self.piano_rate.get()
        except TclError:
            piano_rate = DEFAULT_PIANO_RATE
        script_file = self.files_listbox.get(self.files_listbox.curselection()) if self.files_listbox.curselection() else ""
        cfg = {'left_comm_port': self.left_comm_port.get(),
               'left_comm_disabled': self.left_comm_disabled.get(),
               'right_comm_port': self.right_comm_port.get(),
               'right_comm_disabled': self.right_comm_disabled.get(),
               'config_file': self.config_file.get(),
               'script_file': script_file, #self.files_listbox.get(self.files_listbox.curselection()),
               'script_loops': piano_loops,
               'script_rate': piano_rate,
               'log_level': self.log_level.get()}

        # Send dict with config & message to queue
        queue_obj = {'config': cfg, 'message': msg}
        self.uki_mm_thread_queue.put(queue_obj)

    def trigger_quit(self):
        self.add_to_gui_queue('QUIT')
        self.master.quit()

    def trigger_script(self):
        self.add_to_gui_queue('PLAY')

    def trigger_stop(self):
        self.add_to_gui_queue('STOP')
        self.input_source.set('None')
        self.input_changed()

    def trigger_reset(self):
        self.add_to_gui_queue('RESET')

    def trigger_restart(self):
        self.add_to_gui_queue('RESTART')

    def input_changed(self):
        self.add_to_gui_queue(self.input_source.get())
        play_state = ACTIVE if self.input_source.get() == 'CSV' else DISABLED
        self.play_button.config(state=play_state)  # grey out play button

    def update_filenames(self):
        self.script_files = glob.glob(os.path.join(self.path.get(), '*.[cC][sS][vV]'))
        self.files_listbox.delete(0, END)
        for filename in self.script_files:
            self.files_listbox.insert(END, os.path.split(filename)[1])

    def process_queue(self):
        # Add incoming log messages to the GUI in scrollbox
        while self.gui_queue.qsize():
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

        # Add current config dict to outgoing queue to update Uki MM task
        self.add_to_gui_queue()




