from binascii import crc32

from mobi.mtld.da.carrier.bucket_type import BucketType
from mobi.mtld.da.carrier.byte_reader import ByteReader
from mobi.mtld.da.carrier.carrier_data_type import CarrierDataType
from mobi.mtld.da.exception.data_file_exception import DataFileException
from mobi.mtld.da.data_type import DataType
from mobi.mtld.da.property import Property
from mobi.mtld.da.property_name import PropertyName


class BucketHandler(object):
    _NO_VALUE                = -1
    _NO_CONTAINER            = 0
    _ORDER_SET_CONTAINER     = 1   
    CRC32_DOES_NOT_MATCH     = 'CRC-32 does not match for bucket "%s".'
    _property_names           = None
    _propertyStringNames     = None
    _propertyValues          = None
    _properties              = None
    _treeLefts               = None
    _treeRights              = None
    _treeProperties          = None

    def __init__(self):
        self._property_names = None
        self._propertyStringNames = None
        self._propertyValues = None
        self._properties = None
        self._treeLefts = None
        self._treeRights = None
        self._treeProperties = None
        
    def _needsBuckets(self):
        """
        Checks if all necearry buckets have been supplied and processed
        """
        if(self._property_names != None and self._propertyValues != None and
           self._properties != None and self._treeLefts != None):
           return False
        
        return True 

    def getTreeLefts(self):
        """
        Returns the Radix Trie "left" pointers
        """
        return self._treeLefts

    def getTreeRights(self):
        """
        Returns the Radix Trie "right" pointers
        """
        return self._treeRights

    def getTreeProperties(self):
        """
        Returns the properties used in the Radix Trie nodes
        """
        return self._treeProperties

    def getPropertyNames(self):
        """
        Returns the property names array
        """
        return self._property_names

    def getPropertyNamesAsStrings(self):
        """
        Returns the property names array
        """
        return self._propertyStringNames

    def processBucket(self, bucketId, fileCrc32, bucketData):
        """
        Process a bucket identified by bucketId. The bucket CRC-32
        hash is verified before parsing the bucket data.
        """
        if(fileCrc32 != (crc32(bucketData) & 0xffffffff)):
            raise DataFileException((self.CRC32_DOES_NOT_MATCH % bucketId))

        if(bucketId == BucketType.PROPERTY_NAMES):
            self._processPropertyNamesBucket(bucketData)
        elif(bucketId == BucketType.PROPERTY_VALUES):
            self._processPropertyValuesBucket(bucketData)
        elif(bucketId == BucketType.PROPERTIES):
            self._processPropertiesBucket(bucketData)
        elif(bucketId == BucketType.IPV4_TREE):
            self._processIpv4TreeBucket(bucketData)

    def _processPropertyNamesBucket(self, data):
        """
        The following is the structure of this bucket :
        2b Num of indexed items
        <repeating>
            1b data type of property value
            1b length of name
            ?b property name - ascii string
        </repeating>
        """
        reader = ByteReader(data)
        numItems = reader.getShort()
        self._property_names = []
        self._propertyStringNames = []

        for i in range(0, numItems):
            valueDataType = reader.getByte()
            name = reader.getStringAscii(reader.getByte())
            self._property_names.insert(i, PropertyName(name, valueDataType))
            self._propertyStringNames.insert(i, name.decode("utf-8"))

    def _processPropertyValuesBucket(self, data):
        """
        The following is the structure of this bucket:
        2b Number of indexed items
        <repeating>
        1b container type ID: no container, ordered set etc
	      <if container="no container">
	         1B        property type - int, boolean, string etc
	         1B/2B/4B  length of value bytes --OPTIONAL-- (only applies to some string types)
	         ?B        the converted value, some data types have a fixed length such as (boolean len=1, byte len=1, short len=2, int len=4, float len=4)
	      </if>
	  
	      <elseif container="ordered set">
	        1B   property type - int, boolean, string etc
	        2B   number of items in the set
	        <repeat>
	          <if type=string>
	            1B        property type - the type of string - 
	            1B/2B/4B  length of value bytes --OPTIONAL-- (only applies to some string types)
	          </if>
	          ?B   the converted value, some data types have a fixed length such as (boolean len=1, byte len=1, short len=2, int len=4, float len=4)
	        </repeat>
	      </if>
        </repeating>
        """
        reader = ByteReader(data)
        numItems = reader.getShort()
        self._propertyValues = []

        for i in range(0, numItems):
            prop = None
            containerType = reader.getByte()
            if containerType == self._NO_CONTAINER:
                prop = self._getSingleValueProperty(reader)
            elif containerType == self._ORDER_SET_CONTAINER:
                prop = self._getMultipleValueProperty(reader)

            self._propertyValues.insert(i, prop)
            
    def _getSingleValueProperty(self, reader):
        """
        Read a single-value property value
        """
        dataType = reader.getByte()
        value = self._getPropertyValue(dataType, reader)
        dataType = CarrierDataType.getBaseDataType(dataType)

        return Property(value, dataType)

    def _getMultipleValueProperty(self, reader):
        """
        Read a multi-value property. If the type is a string then the string type
        is read from the data file for each value in order to know how many bytes
        to read.
        """
        dataType = reader.getByte()
        numItems = reader.getShort()

        values = []
        for i in range(0, numItems):
            tempdataType = dataType
            if dataType == DataType.STRING:
                tempdataType = reader.getByte()

            value = self._getPropertyValue(tempdataType, reader)
            values.insert(i, value)

        dataType = CarrierDataType.getBaseDataType(dataType)
        return Property(values, dataType)

    def _processPropertiesBucket(self, data):
        """
        Properties - nameid:valueid
        The following is the structure of this bucket

	  
	    The following is the structure of this bucket:
	  
	     2B   Num of indexed items
	     <repeating>
	         2B num items in collection
	  	      <repeating>
                 4B    property name ID
                 4B    property value ID
	         </repeating>
	     </repeating>
	  
	  
	    The order of the properties is taken as the index for each item. As each
        """
        reader = ByteReader(data)
        numItems = reader.getShort()
        self._properties = []
        
        for i in range(0, numItems):
            props = {}
            numPropVals = reader.getShort()

            for s in range(0, numPropVals):
                propId = reader.getInt()
                valId = reader.getInt()

                if self._property_names[propId] != None:
                    propName = self._property_names[propId]
                    propValue = None

                    if self._propertyValues[valId] != None:
                        propValue = self._propertyValues[valId] 
                    props[propName.name] = propValue

            self._properties.insert(i, props)

    def _processIpv4TreeBucket(self, data):
        """
        Load the data for the IPv4 Tree bucket. This bucket has
        the following structure:
	  
	    These 3 ints repeat for the entire bucket:
	      <repeating>
	         4B properties ID value
	         4B Left value
	         4B Right value
          </repeating>
        """
        reader = ByteReader(data)
        size = int(len(data) / 12)
        self._treeRights = []
        self._treeLefts = []
        self._treeProperties = []

        for i in range(0, size):
            propsId = reader.getInt()
            self._treeLefts.insert(i, reader.getInt())
            self._treeRights.insert(i, reader.getInt())
            prop = None

            if(propsId != self._NO_VALUE):
                prop = self._properties[propsId]

            self._treeProperties.insert(i, prop)

    def _getPropertyValue(self, dataType, reader):
        """
        Read the appropriate property from the ByteReader depending on the
        data type. All of the primitive types are fixed length. In addition
        there are five fixed length UTF8 string values and other special types
        for strings that are less than certain lengths.
        """
        value = None

        if(dataType == DataType.BOOLEAN):
            value = reader.getBoolean()
        elif(dataType == DataType.BYTE):
            value = reader.getByte()
        elif(dataType == DataType.SHORT):
            value = reader.getShort()
        elif(dataType == DataType.INTEGER):
            value = reader.getInt()
        elif(dataType == DataType.LONG):
            value = reader.getLong()
        elif(dataType == DataType.FLOAT):
            value = reader.getFloat()
        elif(dataType == DataType.DOUBLE):
            value = reader.getDouble()
        elif(dataType == CarrierDataType.STRING_1_BYTE_FIXED):
            value = reader.getStringUtf8(1)
        elif(dataType == CarrierDataType.STRING_2_BYTE_FIXED):
            value = reader.getStringUtf8(2)
        elif(dataType == CarrierDataType.STRING_3_BYTE_FIXED):
            value = reader.getStringUtf8(3)
        elif(dataType == CarrierDataType.STRING_4_BYTE_FIXED):
            value = reader.getStringUtf8(4)
        elif(dataType == CarrierDataType.STRING_5_BYTE_FIXED):
            value = reader.getStringUtf8(5)
        elif(dataType == CarrierDataType.STRING_LEN_BYTE):
            value = reader.getStringUtf8(reader.getByte())
        elif(dataType == CarrierDataType.STRING_LEN_SHORT):
            value = reader.getStringUtf8(reader.getShort())
        elif(dataType == CarrierDataType.STRING_LEN_INT):
            value = reader.getStringUtf8(reader.getInt())
        elif(dataType == DataType.STRING):
            value = reader.getStringUtf8(reader.getShort())
        else:
            reader.skip(reader.getShort())

        return value
