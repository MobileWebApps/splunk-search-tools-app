import splunk_config_handler as ch
import splunk.admin as admin

'''
# Sets a ConfigHandler that supports all settings in
# app_utils.APP_CONFIG_FILE
'''
admin.init(ch.buildConfigHandler(), admin.CONTEXT_NONE)
