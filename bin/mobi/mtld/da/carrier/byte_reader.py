from struct import unpack_from

class ByteReader:
    _buff = ""
    _position = 0

    def __init__(self, data):
        self._buff = data

    def skip(self, offset):
        self._position += offset

    def getShort(self):
        data = unpack_from("<h", self._buff, self._position)[0]
        self._position += 2
        return data    

    def getInt(self):
        data = unpack_from("<i", self._buff, self._position)[0]
        self._position += 4
        return data

    def getIntUnsigned(self):
        data = unpack_from("<I", self._buff, self._position)[0]
        self._position += 4
        return data

    def getLong(self):
        data = unpack_from("<l", self._buff, self._position)[0]
        self._position += 8
        return data

    def getFloat(self):
        data = unpack_from("<f", self._buff, self._position)[0]
        self._position += 4
        return data

    def getDouble(self):
        data = unpack_from("<d", self._buff, self._position)[0]
        self._position += 8
        return data

    def getByte(self):
        data = unpack_from("<B", self._buff, self._position)[0]
        self._position += 1
        return data

    def getBytes(self, length):
        data = unpack_from(("<%dB" % length), self._buff, self._position)
        self._position += length
        return data

    def getStringAscii(self, length):
        data = unpack_from(("<%ds" % length), self._buff, self._position)[0]
        self._position += length
        return data

    def getStringUtf8(self, length):
        data = unpack_from(("<%ds" % length), self._buff, self._position)[0]
        self._position += length
        return data
