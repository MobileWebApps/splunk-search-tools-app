from os import path
from socket import inet_aton, error
from struct import unpack

from mobi.mtld.da.carrier.byte_reader import ByteReader
from mobi.mtld.da.carrier.bucket_handler import BucketHandler
from mobi.mtld.da.carrier.bucket_type import BucketType
from mobi.mtld.da.exception.data_file_exception import DataFileException


class CarrierData(object):
    _MAGIC_NUMBER               = b'DA'
    _FILE_ID                    = 1
    _START_BYTES_LEN            = 5
    _CREATION_DATE_LEN          = 24
    _BUCKET_START_BYTES_LEN     = 10

    _copyright                  = ""
    _creationDate               = ""
    _version                    = ""
     # data for the IPv4 Radix Tree
    _NULL_PTR                   = -1
    _ROOT_PTR                   = 0
    _MAX_IPV4_BIT               = 0x80000000
    _treeLefts                  = []
    _treeRights                 = []
    _treeProperties             = []
    _property_names              = None
    _propertyStringNames        = None

    # error messages
    _PROBLEM_READING_DATA_FILE  = 'Problem reading data file.'
    _INVALID_DATA_FILE          = 'Invalid data file.'

    _data                       = None
    _cursor                     = 0

    _propertyStringNames        = None
    _property_names              = None

    def load_data_from_file(self, filePath):
       try:
           fsize = path.getsize(filePath)
           _hdl = open(filePath, 'rb')
           self._data = _hdl.read(fsize)
           _hdl.close()
           self._readHeader()
           self._readBuckets()
       except(Exception) as ex:
           raise DataFileException(self._PROBLEM_READING_DATA_FILE)

    def _readHeader(self):
        """
        The header of the file contains the following data:
	     2B  DA (US-ASCII)
	     1B  File type ID (1: carrier data, 2:some other data.... etc)
	     2B  Header length - the total size of the header including the preceding bytes
	     2B  Length of copyright text
	     ?B  Copyright (US-ASCII) "(c) Copyright 2013 - Afilias Technologies Ltd"
	     24B Creation date (US-ASCII) "2013-08-07T15:36:44+0000"
	     1B  Version, major
	     1B  Version, minor
	     4B  Licence ID
	     4B  CRC-32 - all data after first bucket offset
        """
        headerLength = self._checkFileTypeGetHeaderLength(self._data[:self._START_BYTES_LEN])
        reader = ByteReader(self._data[self._START_BYTES_LEN:])
        self._cursor = headerLength
        self._copyright = reader.getStringAscii(reader.getShort())
        if type(self._copyright) == bytes:
            self._copyright = self._copyright.decode("utf-8")
        self._creationDate = reader.getStringAscii(self._CREATION_DATE_LEN)
        if type(self._creationDate) == bytes:
            self._creationDate = self._creationDate.decode("utf-8")
        self._version = ("%s.%s" % (str(reader.getByte()), str(reader.getByte())))
        if type(self._version) == bytes:
            self._version = self._version.decode("utf-8")

        licenceId = reader.getInt()


    def _checkFileTypeGetHeaderLength(self, startBytes):
        """
        Check the first few bytes to make sure we are opening
        a Carrier Identification file.
        """
        reader = ByteReader(startBytes)
        fileMagic = reader.getStringAscii(2)
        fileTypeId = reader.getByte()

        if fileMagic != self._MAGIC_NUMBER or fileTypeId != self._FILE_ID:
            raise DataFileException(self._INVALID_DATA_FILE)

        return reader.getShort()

    def _readBuckets(self):
        """
	    Each bucket is comprised of the following. The BucketHandler is
	    responsible for actually parsing the data in each bucket. This method
	    keeps reading until either the end of the file or until all necessary
	    buckets have been read. It will skip buckets with IDs it does not
	    recognise to hopefully future proof the API against possible additions to
	    the data file
	  
	    Bucket structure:
	  
	     2B  Bucket ID
	     4B  CRC-32 checksum - NOTE: unsigned int!
	     4B  Length of the data
	     ?B  Data
        """
        bucketHandler = BucketHandler()
        
        while(bucketHandler._needsBuckets()):
            reader = ByteReader(self._data[self._cursor:(self._cursor + self._BUCKET_START_BYTES_LEN)])
            self._cursor += self._BUCKET_START_BYTES_LEN
            bucketId = reader.getShort()
            vcrc32 = reader.getIntUnsigned()
            length = reader.getInt()

            if BucketType.isValidId(bucketId):
                bucketHandler.processBucket(bucketId, vcrc32, self._data[self._cursor:(self._cursor + length)])
            
            self._cursor += length

        self._treeLefts = bucketHandler.getTreeLefts()
        self._treeRights = bucketHandler.getTreeRights()
        self._treeProperties = bucketHandler.getTreeProperties()

        self._propertyStringNames = bucketHandler.getPropertyNamesAsStrings()
        self._property_names = bucketHandler.getPropertyNames()

    def getProperties(self, key):
        """
        Selects a value for a given IPV4 address, traversing tree
        and choosing most specific value available for a given
        address.
        """
        try:
            key = unpack('>L', inet_aton(key))[0]
        except(error):
            return None

        bit = self._MAX_IPV4_BIT
        value = None
        node = self._ROOT_PTR

        while(node != self._NULL_PTR):
            if self._treeProperties[node] != None:
                value = self._treeProperties[node]

            if (key & bit) != 0:
                node = self._treeRights[node]
            else:
                node = self._treeLefts[node]
            bit >>= 1

        return value

    def getPropertyNames(self):
        """
        Return a list of all the property names
        """
        return self._property_names

    def getPropertyNamesAsStrings(self):
        """
        Return a list of all the property names
        """
        return self._propertyStringNames

    def getCopyright(self):
        """
        Return the copyright
        """
        return self._copyright

    def getCreationDate(self):
        """
        Return the creation of date
        """
        return self._creationDate

    def getVersion(self):
        """
        Return the version
        """
        return self._version

