import logging
import logging.handlers
from os import environ

'''
Usage:

    # Setup the handler
    logger = setup_logger(level=logging.INFO)
    logger.error('Test')

'''

DEBUG = logging.DEBUG
INFO = logging.INFO
WARN = logging.WARN
ERROR = logging.ERROR

DEFAULT_FORMATTER = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
DEFAULT_LOG_FILE = 'application.log'

def get_rotating_file_handler(log_file_path=DEFAULT_LOG_FILE):
    return logging.handlers.RotatingFileHandler(log_file_path, maxBytes=25000000, backupCount=5)

def setup_file_logger(name='application', level=logging.INFO, log_file=DEFAULT_LOG_FILE, formatter = DEFAULT_FORMATTER):
    return setup_logger(name=name, level=level, log_handler=get_rotating_file_handler(log_file), formatter = formatter)

def setup_logger(name='application', level=logging.INFO, log_handler=get_rotating_file_handler(), formatter = DEFAULT_FORMATTER):

    logger = logging.getLogger(name)
    logger.propagate = False # Prevent the log messages from being duplicated in the python.log file
    logger.setLevel(level)
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    return logger
