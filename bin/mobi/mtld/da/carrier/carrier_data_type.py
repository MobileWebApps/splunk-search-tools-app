from mobi.mtld.da.data_type import DataType

class CarrierDataType(DataType):
    """
    These are special types - used to optimise adding of string
    values - these are internal only, they should not be exposed
    to the customer.
    """
    STRING_LEN_BYTE        = 100
    STRING_LEN_SHORT       = 101
    STRING_LEN_INT         = 102
    STRING_1_BYTE_FIXED    = 103
    STRING_2_BYTE_FIXED    = 104
    STRING_3_BYTE_FIXED    = 105
    STRING_4_BYTE_FIXED    = 106
    STRING_5_BYTE_FIXED    = 107

    _START_STRING_ID = STRING_LEN_BYTE
    _END_STRING_ID = STRING_5_BYTE_FIXED

    @staticmethod
    def getBaseDataType(dataTypeId):
        if(dataTypeId >= CarrierDataType._START_STRING_ID and
           dataTypeId <= CarrierDataType._END_STRING_ID):
           dataTypeId = CarrierDataType.STRING

        return dataTypeId

