from struct import unpack
from socket import *

from mobi.mtld.da.exception.invalid_property_name_exception import InvalidPropertyNameException
from mobi.mtld.da.carrier.carrier_data import *
from mobi.mtld.da.property import *


class CarrierApi(object):

    """
    A list of HTTP headers to choose the original client IP
    address from. In addition to these the REMOTE_ADDR is
    also used as a final fallback.
    """
    _HEADERS_TO_CHECK   = [
        "x-forwarded-for",
        "client-ip",
        "x-client-ip",
        "rlnclientipaddr",
        "proxy-client-ip",
        "wl-proxy-client-ip",
        "x-Forwarded",
        "forwarded-for",
        "forwarded"
    ]

    _VERSION            = "1.0.1"

    _PRIVATE = ([0, 4294967295],
                [ 2130706432 , 4278190080 ],
                [ 3232235520 , 4294901760 ],
                [ 2886729728 , 4293918720 ],
                [ 167772160 , 4278190080 ],
                [ 2851995648, 65535])

    _data               = None

    _MISSING_DATA_EX    = "No data file loaded, load data with load_data_from_file()"
    _INVALID_PROP_EX    = "Property name \"%s\" does not exist"

    def load_data_from_file(self, path):
        """
        Load the data file from the provided path. The data file is reloaded
        every tme this method is called.
        """
        self._data = CarrierData()
        self._data.load_data_from_file(path)

    def get_data_file_copyright(self):
        """
        Returns the data file copyright text
        """
        self._dataLoaded()
        return self._data.getCopyright()

    def get_data_file_creation_date(self):
        """
        Returns the data file creation date in ISO8601 format
        """
        self._dataLoaded()
        return self._data.getCreationDate()

    def get_data_file_version(self):
        """
        Returns the version of the data file
        """
        self._dataLoaded()
        return self._data.getVersion()

    def get_properties(self, ipv4):
        """
        Get the Carrier properties for a given IP address.
        """
        if(type(ipv4) is dict):
            ipv4 = self.get_ip(ipv4)

        props = None

        self._dataLoaded()
        
        if ipv4 != None:
         props = self._data.getProperties(ipv4)

        return props

    def get_property(self, ipv4, propertyName):
        """
        Try and get a specific property for a given IP address.
        Note : If mutiple properties are needed for the same IP
        it is more efficient to call properties() once than
        repeated calls to property()
        """
        if(type(propertyName) != str):
            propertyName = propertyName.decode("utf-8")
        if(type(ipv4) is dict):
            ipv4 = self.get_ip(ipv4)

        self._dataLoaded()
        self.property_name_exists(propertyName)

        prop = None
        if ipv4 != None:
            props = self._data.getProperties(ipv4)
            if props != None and propertyName in props:
                prop = props[propertyName]

        return prop

    def get_property_names(self):
        """
        A set of all the possible property names.
        The set contains PropertyName objects that
        each have a string name and an associated 
        data type.
        """
        self._dataLoaded()
        return self._data.getPropertyNames()

    def _dataLoaded(self):
        """
        Checks to make sure the data file is loaded.
        """
        if self._data is None:
            raise DataFileException, self._MISSING_DATA_EX

    def _property_name_exists(self, propertyName):
       """
       Check if the given propertyName is not None and exists
       in the data file. Calls to this method must be sure that
       the data object is already loaded.
       """
       if propertyName not in self._data.getPropertyNamesAsStrings(): 
           raise InvalidPropertyNameException((self._INVALID_PROP_EX % propertyName))

    @staticmethod
    def _normaliseKeys(keyVals):
        """
        Normalise the keys in the passed in key value map.
        This lower-cases the keys, replaces "_" with "-"
        and removes any HTTP_ prefix.
        """
        for headerName in keyVals:
            value = keyVals[headerName]
            del(keyVals[headerName])

            headerName = headerName.lower()
            headerName = headerName.replace('_', '-')
            headerName = headerName.replace('http-', '')

            if type(value) == bytes:
                value = value.decode("utf-8")

            keyVals[headerName] = value

        return keyVals

    @staticmethod
    def get_ip(keyVals):
        """
        Extracts and cleans an IP address from the headerValue.
        Some headers such as "X-Forwarded-For" can contain multiple
        IP addresses such as:
        clientIP, proxy1, proxy2...
        """
        ip = None
        keyVals = CarrierApi._normaliseKeys(keyVals)

        if keyVals != None:
            for headerName in CarrierApi._HEADERS_TO_CHECK:
                if headerName not in keyVals:
                    continue
                ip = CarrierApi.extract_ip(headerName, keyVals[headerName])
                if ip != None:
                    break

        return ip

    def property_name_exists(self, propertyName):
        property_names = self._data.getPropertyNamesAsStrings()

        if(property_names == None or not propertyName in property_names):
            raise InvalidPropertyNameException((self._INVALID_PROP_EX % propertyName))

    @staticmethod
    def is_public_ip(ipv4):
        """
        An IP address is considered public if it is not
        in any of the following ranges:
	    1) any local address
	      IP:  0
	 
	    2) a local loopback address
	      range:  127/8
	   
	    3) a site local address i.e. IP is in any of the ranges:
	      range:  10/8 
	      range:  172.16/12 
	      range:  192.168/16
	   
	    4) a link local address 
        """
        try:
            f = unpack("!I", inet_aton(ipv4))[0]
        except(Exception) as ex:
            return False

        for rg in CarrierApi._PRIVATE:
            if f & rg[1] == rg[0]:
                return False

        return True

    @staticmethod
    def extract_ip(headerName, headerValue):
        if headerValue != "" and headerValue != None:
            if headerName.lower() == 'x-forwarded-for':
                parts = headerValue.split(',')
                if parts != None:
                    headerValue = parts[0]

            headerValue = headerValue.strip()

            if headerValue != None and CarrierApi.is_public_ip(headerValue):
                return headerValue

        return None

