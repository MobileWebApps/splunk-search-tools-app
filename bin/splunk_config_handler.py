from util.apache_config import read_config_file
import app_utils


DEFAULT_APP_CONFIG_FILE =  app_utils.APP_CONFIG_FILE
LOCAL_APP_PATH = app_utils.APP_PATH


def buildConfigHandler(config_file=DEFAULT_APP_CONFIG_FILE, supported_fields='auto'):
    '''
    # Closure to create a configurable MConfigHandler
    '''

    import splunk.admin as admin

    class ConfigurableConfigHandler(admin.MConfigHandler):
        '''
        # Handles the parameters in the configuration page.

              handleList method: lists configurable parameters in the configuration page
              corresponds to handleractions = list in restmap.conf

              handleEdit method: controls the parameters and saves the values
              corresponds to handleractions = edit in restmap.conf

        '''

        def setup(self):
            '''
            # Set up supported arguments
            '''

            _supported_fields = supported_fields

            if supported_fields=='auto':
                _config_file = '%s/default/%s.conf' % (LOCAL_APP_PATH, DEFAULT_APP_CONFIG_FILE)
                config, all_sections, all_options, merged_options = read_config_file(default_config_file=_config_file)
                _supported_fields = merged_options


            if self.requestedAction == admin.ACTION_EDIT:
                for arg in _supported_fields:
                    self.supportedArgs.addOptArg(arg)


        def handleList(self, confInfo):
            '''
            # Read the initial values of the parameters from the custom file
            # config_file, and write them to the setup screen.

            If the app has never been set up,
                uses .../<appname>/default/config_file.

            If app has been set up, looks at
                .../local/config_file first, then looks at
            .../default/config_file only if there is no value for a field in
                .../local/config_file

            For boolean fields, may need to switch the true/false setting.

            For text fields, if the conf file says None, set to the empty string.
            '''
            confDict = self.readConf(config_file)
            if None != confDict:
                for stanza, settings in confDict.items():
                    for key, val in settings.items():
                        if '_boolean' in key:
                            if val.lower() == 'false':
                                val = '0'
                            elif val.lower() == 'true':
                                val = '1'
                            else:
                                val = '0'
                                # raise Exception('[Error] Boolean configuration can only contain True | False values - app_config_handler.py')

                        if val in [None, '']:
                            val = ''
                        confInfo[stanza].append(key, val)


        def handleEdit(self, confInfo):
            '''
            # After user clicks Save on setup screen, take updated parameters,
            # normalize them, and save them somewhere
            '''
            try:
                stanza_endpoint_name = self.callerArgs.id
                args = self.callerArgs

                # Transform boolean values
                for key in self.callerArgs.data:
                    if '_boolean' in key:
                        if self.callerArgs.data[key][0] == '0':
                            self.callerArgs.data[key][0] = 'False'
                        else:
                            self.callerArgs.data[key][0] = 'True'

                    # Transform empty values
                    if self.callerArgs.data[key][0] in [None, '']:
                        self.callerArgs.data[key][0] = ''

                self.writeConf(config_file, stanza_endpoint_name, self.callerArgs.data)

            except Exception, e:
                msg = 'stanza_endpoint_name: %s' % stanza_endpoint_name
                msg+= 'Value: %s' % (str(self.callerArgs.data))
                #logger.error("Cant write to config file %s\n config_file: %s\n stanza_endpoint_name: %s\n value:%s" % (config_file, stanza_endpoint_name, self.callerArgs.data))
                raise e(msg)



    return ConfigurableConfigHandler
