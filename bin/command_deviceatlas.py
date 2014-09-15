#!/usr/bin/env python

import sys

from splunklib.searchcommands import \
    dispatch, StreamingCommand, Configuration, Option
from device_atlas_service import DeviceAtlasService
import app_utils


@Configuration()
class DeviceatlasCommand(StreamingCommand):
    """
    # Check file default/searchbnf.conf for documentation
    """
    notFoundMessage = Option(
        require=False, default='[DeviceAtlas] Property not found!')


    _app_dir = app_utils.APP_PATH
    _store = _app_dir+'/default/data'


    config, all_sections, all_options, merged_options = app_utils.get_app_config()

    _device_atlas_gzip_download_url = config.get('deviceatlas','device_atlas_gzip_download_url')
    _json_data_file_path = config.get('deviceatlas','json_data_file_path')
    _enable_daily_update = config.get('deviceatlas','enable_daily_update_boolean')


    if _json_data_file_path and _json_data_file_path.startswith('default'):
        _da_json = _app_dir+ "/"+_json_data_file_path
    else:
        _da_json = _json_data_file_path



    def stream(self, search_events):
        """
        # Process Splunk Search Events
        """
        self.logger.debug('%s: %s' % (self.__class__.__name__, self))  # logs command line

        if not search_events:
            return

        _da = DeviceAtlasService(self._da_json,self._device_atlas_gzip_download_url,
                                 self._store, app_utils.parseBoolean(self._enable_daily_update))


        for event in search_events:

            useragent = event.get('useragent',None)
            #event["DEBUG"] = 'Fields: %s ::: UAA:%s ' % (self.fieldnames,useragent)

            if not useragent:
                yield event
                continue

            for fieldname in self.fieldnames:
                try:
                    _da.load_device_atlas_db()
                    prop = _da.get_property(useragent,fieldname)

                    if prop is None:
                        event[fieldname] = self.notFoundMessage
                    else:
                        event[fieldname] = prop

                except Exception, e:
                    event[fieldname] = "[Error] " + str(e)

            yield event




try:
    dispatch(DeviceatlasCommand, sys.argv, sys.stdin, sys.stdout, __name__)
except Exception, e:
    # Catch any exception, log it and also return a simplified version back to splunk (should be displayed in red at the top of the page)
    import traceback
    stack =  traceback.format_exc()
    raise e("Dispatch Error : Traceback: " + str(stack))
