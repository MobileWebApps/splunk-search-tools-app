from os import getcwd, path, environ
from util.apache_config import read_config_file, get_config_string, parseBoolean #do not remove
import util.log as log
import csv, sys, os

SPLUNK_HOME     = path.normpath(environ["SPLUNK_HOME"])

APP_NAME        = 'splunk-search-tools-app'
APP_CONFIG_FILE = 'appsetup'

APP_PATH        = path.join(SPLUNK_HOME, 'etc', 'apps', APP_NAME)
APP_LOG_FILE    = path.join(SPLUNK_HOME, 'var', 'log', 'splunk', APP_NAME+'.log')

LOCAL_APP_PATH = _app_dir = getcwd() + '/..'

DEBUG_LOGGER = log.setup_file_logger(level=log.DEBUG, log_file=APP_LOG_FILE)



def get_app_config(file_name=APP_CONFIG_FILE, app_home_dir=APP_PATH):
    '''
    # Reads a Splunk config file by merging settings in the default and local
    # app folders
    :usage: config, all_sections, all_options, merged_options = read_config_file()
    '''

    default_config_file = path.join(app_home_dir, 'default', file_name + '.conf')
    local_config_file = path.join(app_home_dir, 'local', file_name + '.conf')

    return read_config_file(default_config_file, local_config_file)



def generateErrorResults(errorStr):
    '''
    # Generates a properly formatted error message for use on
    # outputResults() methods.
    '''
    h = ["ERROR"]
    results = [ {"ERROR": errorStr} ]

    if sys.platform == 'win32':
        import msvcrt
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


    dw = csv.DictWriter(sys.stdout, h)
    dw.writerow(dict(zip(h, h)))
    dw.writerows(results)
    # return [{"ERROR": errorStr}]
    return None



########################################################################
#    Main
########################################################################
'''
config, all_sections, all_options, merged_options = get_app_config()
print get_config_string(config)
'''