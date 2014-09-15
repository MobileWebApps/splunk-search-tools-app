from mobi.mtld.da.device.device_api import DeviceApi
from datetime import datetime, timedelta
import cPickle as yaml
import urllib, gzip




class DeviceAtlasService(object):
    '''
    # Device Atlas Helper
    '''

    _device_api = DeviceApi()

    def __init__(self,
                 json_data_file_path='./deviceatlas.json',
                 device_atlas_gzip_download_url = None,
                 data_folder='./',
                 enable_daily_update = True
    ):

        self._device_atlas_gzip_download_url = device_atlas_gzip_download_url
        self._json_data_file_path = json_data_file_path
        self._data_folder = data_folder + '/store.pickle'
        self._enable_daily_update = enable_daily_update



    def update_device_atlas_db(self):
        '''
        # Checks if Device Atlas json file needs to be updated
        # and executes the update
        '''

        if not self._enable_daily_update or not self._device_atlas_gzip_download_url:
            return

        # Check if it is time to download...
        try:
            data = yaml.load(open(self._data_folder, 'rb'))
            last_check = data.get('last_device_atlas_db_download',None)
        except:
            data = {}
            last_check = None

        now = datetime.now()
        update = True;

        if last_check:
            if (now - last_check) <= timedelta(days = 1):
                update = False

        # Download and extract DA json file...
        if update:
            self.download_device_atlas_db()


        # Update last download time...
        data['last_device_atlas_db_download'] = now
        yaml.dump(data, open(self._data_folder, 'wb'))



    def download_device_atlas_db(self):
        '''
        # Download and extract DA json file...
        '''

        print "downloading and updating device atlas file..."
        zipf = '%s.gzip' % self._json_data_file_path
        urllib.urlretrieve (self._device_atlas_gzip_download_url, zipf)

        with gzip.open(zipf, 'rb') as gfile:
            with open(self._json_data_file_path, 'wb') as dbfile:
                dbfile.write(gfile.read())



    def load_device_atlas_db(self):
        '''
        # Loads DA json file
        '''
        self.update_device_atlas_db()
        self._device_api.load_data_from_file(self._json_data_file_path)



    def get_property(self, useragent, property):
        '''
        # Return a single property for a device
        # headers = {"HEADER NAME": "HEADER VALUE"}
        '''
        headers = {
            "User-Agent": useragent
        }
        return self.get_property_from_headers(headers, property)


    def get_property_from_headers(self, headers, property):
        properties = self._device_api.get_properties(headers)
        return properties.get(property)




    def get_properties(self, useragent):
        '''
        # Return all properties for a device
        # headers = {"HEADER NAME": "HEADER VALUE"}
        '''
        headers = {
            "User-Agent": useragent
        }
        return self.get_properties_from_headers(headers)


    def get_properties_from_headers(self, headers):
        return self._device_api.get_properties(headers)




    def display_property_names(self):
        '''
        # Displays all DA properties
        '''
        creation_timestamp_posix = self._device_api.get_data_creation_timestamp()
        creation_timestamp = datetime.fromtimestamp(creation_timestamp_posix)
        print creation_timestamp.strftime('%Y-%m-%d %H:%M:%S')



        print('---------------')
        print('Property names:')
        print('---------------')

        property_names = self._device_api.get_property_names()

        for property_name in property_names:
            print(property_name.name + " (" + property_name.data_type() + ")")




########################################################################
#    Main
########################################################################
'''

_da_license = 'INSERT_LICENCE_HERE'
_da_db_url = 'http://deviceatlas.com/getJSON.php?licencekey=%s&format=gzip&data=my' % _da_license

_app_dir = '..'
_store = _app_dir+'/default/data'
_da_db = _app_dir+"/default/data/deviceatlas.json"


da = DeviceAtlasService(_da_db,_da_db_url,_store)
da.load_device_atlas_db()
user_agent = "Mozilla/5.0 (Linux; U; Android 2.3.3; en-gb; GT-I9100 Build/GINGERBREAD) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1"

print 'Browser: %s' % da.get_property(user_agent,'browserName')
print

properties = da.get_properties(user_agent)


def printp(key, value):
    print '%s:%s' % (key, value)

for key, value in properties.iteritems():
    printp(key,value)

'''