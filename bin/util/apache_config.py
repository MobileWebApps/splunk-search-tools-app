import ConfigParser
from itertools import chain

def read_config_file(default_config_file=None, aditional_config_files=None):

    config = ConfigParser.ConfigParser(allow_no_value=True)

    if default_config_file:
        config.readfp(open(default_config_file))

    if aditional_config_files:
        config.read(aditional_config_files)

    all_sections = config.sections()
    all_options = [config.options(section) for section in all_sections]
    merged_options = list(chain.from_iterable(all_options))


    return config, all_sections, all_options, merged_options


def get_config_string(config):

    str =''
    for section in config.sections():
        for option in config.options(section):
            str+= '['+section+ '] ' + option + '=' + config.get(section,option) + '\n'

    return str



def parseBoolean(v):
    if not v:
        return None
    return v.lower() in ("yes", "true", "t", "1")
