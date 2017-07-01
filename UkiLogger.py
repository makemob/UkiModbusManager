#!/usr/bin/env python
# -*- coding: utf_8 -*-
"""
 UkiModbusManager Logger

 Chris Mock, 2017

 Implements console logging and optional queue logging

 Licensed under GNU General Public License v3.0, https://www.gnu.org/licenses/gpl-3.0.txt

"""

import logging
import logging.handlers


def prep_handler(handler, log_level):
    handler.setLevel(log_level)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    return handler


def get_logger(log_level=logging.DEBUG, queue=None):
    logger = logging.getLogger('uki_logger')
    logger.setLevel(log_level)
    logger.addHandler(prep_handler(logging.StreamHandler(), log_level))

    if queue is not None:
        logger.addHandler(prep_handler(logging.handlers.QueueHandler(queue), log_level))

    return logger



# logger.debug('debug message')
# logger.info('info message')
# logger.warn('warn message')
# logger.error('error message')
# logger.critical('critical message')
