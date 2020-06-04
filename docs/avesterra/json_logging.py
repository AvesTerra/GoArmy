#!/usr/bin/env python3

"""json_logging.py: utility functions for setting up logging via json
"""

__author__ = "Dave Bridgeland"
__copyright__ = "Copyright 2018-2019, Georgetown University"
__credits__ = ["Dave Bridgeland"]

__maintainer__ = "Dave Bridgeland"
__email__ = "dave@hangingsteel.com"
__status__ = "Prototype"

import logging
import logging.handlers
import time
import json

# An alternative formatter, based on bit.ly/2ruBlL5
class _JsonSafeFormatter(logging.Formatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    def format(self, record):
        # To make the message safe for json
        record.msg = json.dumps(record.msg)[1:-1]
        return super().format(record)


def initialize_logging(file_name):
    """Initialize the logging system, both to file and to console for errs"""
    if _logging_not_initialized(): 
        root_logger = logging.getLogger() 
        initialize_logging_to_file(file_name, root_logger)
        _initialize_logging_errors_to_console(root_logger)

def _logging_not_initialized():
    """Has logging already been initialized?"""
    return len(logging.getLogger().handlers) == 0

def initialize_logging_to_rotating_file(logfile, logger, maxBytes):
    """Initialize the logging sytem, rotating files after 1M."""
    jsonhandler = logging.handlers.RotatingFileHandler(
        logfile, maxBytes=maxBytes, backupCount=10)
    _initialize_logging_to_file_handler(logger, jsonhandler)

def initialize_logging_to_file(logfile, logger):
    """Initialize the logging system, using a json format for log files"""
    jsonhandler = logging.FileHandler(logfile, mode='w')
    _initialize_logging_to_file_handler(logger, jsonhandler)

def _initialize_logging_to_file_handler(logger, handler):
    """Initialize json logging to file handler, already defined."""
    handler.setLevel(logging.DEBUG) 
    formatter = _JsonSafeFormatter("""{
        "asctime": "%(asctime)s",
        "levelname": "%(levelname)s",
        "thread": "%(thread)d",
        "filename": "%(filename)s",
        "funcName": "%(funcName)s",
        "message": "%(message)s"
        }""")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def _initialize_logging_errors_to_console(logger):
    """Log errors to the console, in a simple single-line format"""
    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)
    ch.setFormatter(logging.Formatter('Error: %(asctime)s - %(message)s'))
    logger.addHandler(ch)
