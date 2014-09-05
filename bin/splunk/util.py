# coding=utf-8
#
# Main utility module for general Splunk stuff
#

from datetime import timedelta, tzinfo, datetime
import time
import re
import os, sys
import math
import subprocess
import urllib
from UserDict import UserDict

FIELD_DELIMITER = ","
FIELD_ESCAPE    = "\\"
FIELD_QUOTE     = "\""
FIELD_DELIMITER_CHARS = " ,\\"

def normalizeBoolean(input, enableStrictMode=False, includeIntegers=True):
    '''
    Tries to convert a value to Boolean.  Accepts the following pairs:
    true/false t/f/ 0/1 yes/no on/off y/n

    If given a dictionary, this function will attempt to iterate over the dictionary
    and normalize each item.
    
    If enableStrictMode is True, then a ValueError will be raised if the input
    value is not a recognized boolean.

    If enableStrictMode is False (default), then the input will be returned
    unchanged if it is not recognized as a boolean.  Thus, they will have the
    truth value of the python language.
    
    NOTE: Use this method judiciously, as you may be casting integer values
    into boolean when you don't want to.  If you do want to get integer values, 
    the idiom for that is:
    
        try: 
            v = int(v)
        except ValueError:
            v = splunk.util.normalizeBoolean(v)
            
    This casts integer-like values into 'int', and others into boolean.
    '''
    
    trueThings = ['true', 't', 'on', 'yes', 'y']
    falseThings = ['false', 'f', 'off', 'no', 'n']

    if includeIntegers:
        trueThings.append('1')
        falseThings.append('0')
        
    def norm(input):
        if input == True: return True
        if input == False: return False
        
        try:
            test = input.strip().lower()
        except:
            return input

        if test in trueThings:
            return True
        elif test in falseThings:
            return False
        elif enableStrictMode:
            raise ValueError, 'Unable to cast value to boolean: %s' % input
        else:
            return input


    if isinstance(input, dict):
        for k,v in input.items():
            input[k] = norm(v)
        return input
    else:
        return norm(input)
    

def stringToFieldList(string):
    '''
    Given a string split it apart using the field list rules:
    1) Comma is the default delimiter (space works only for the field_list param on the /search/jobs/<sid>/events endpoint).
    2) All fields that contain the delimiter (space or comma), escape or a double quote char ", must be quoted.
    3) Backslash is used to escape backslashes and double quote characters. All other instances are interpreted as backslash chars.

    For example:
    stringToFieldList('one two, three \\ four "and\" five"')
    literal ["one", "two", "three", "\", "four", 'and" five']
    '''

    if not isinstance(string, basestring):
        return []

    items = []
    item_buffer = []
    in_quote = False
    iterator = enumerate(string)
    for i, c in iterator:

        if c == FIELD_ESCAPE:
            try:
                next_item = iterator.next()[1]
                if next_item in ['"', '\\']:
                    item_buffer.append(next_item)
                    continue
                else:
                    item_buffer.append(FIELD_ESCAPE)
                    c = next_item
            except StopIteration:
                item_buffer.append(c)
                continue

        if c == FIELD_QUOTE: 
            if not in_quote:
                in_quote = True
                continue

            if in_quote:
                in_quote = False
                items.append(''.join(item_buffer))
                item_buffer = []
                continue

        if c in FIELD_DELIMITER_CHARS and not in_quote:
            if len(item_buffer) > 0:
                items.append(''.join(item_buffer))
            item_buffer = []
            continue

        item_buffer.append(c)
        
    if len(item_buffer) > 0:
        items.append(''.join(item_buffer))
        
    return items


def fieldListToString(fieldList, delimiter=FIELD_DELIMITER):
    '''
    Given a list of strings, converts the list into a valid Unicode string compliant with the splunkd field_list attribute.

    A valid field list string is delimited by either comma (default) or space and groups by the double quote char ".
    Backslash escapes " and itself.

    Arguments:
    fieldList -- A list of strings to convert into a valid field list string.

    Example usage:
    >> field_list = ["_raw", "first \ ip", '"weird quoted string"']
    >> fieldListToString(field_list)
    >> '_raw,"first \\ ip","\"weird quoted string\""'

    Returns:
    A Unicode string of all the elements in lst deliminated by the given delimiter.
    '''
    re_escaped = re.escape(FIELD_ESCAPE)
    delimiter_matcher = re.compile("[%s]" % re.escape(FIELD_DELIMITER_CHARS))
    escapable = re.compile("([%s])" % (re_escaped + FIELD_QUOTE))

    output_buffer = []
    for item in fieldList:
        # Convert all items to strings. This allows objects to def a __str__ 
        # method and just work. May raise an exception if something cannot 
        # be converted to a unicode string.
        item = unicode(item)
        item = item.strip()
        if item == '': continue

        # Escape all backslashes or double quotes
        if escapable.search(item):
            item = escapable.sub(re_escaped + r"\1", item)

        # Finally quote the item if needed and return a unicode string.
        if delimiter_matcher.search(item):
            item = u''.join([FIELD_QUOTE, item, FIELD_QUOTE])

        output_buffer.append(item)
    return delimiter.join(output_buffer)


def smartTrim(string, maxLength=50, placeholder='...'):
    '''
    Returns a string trimmed to maxLength by removing characters from the
    middle of the string and replacing with ellipses.
    
    Ex: smartTrim('1234567890', 5) ==> '12...890'
    '''
    
    if not string: return string
    if int(maxLength) < 1: return string
    if len(string) <= maxLength: return string
    if maxLength == 1: return string[0:1] + placeholder

    midpoint = math.ceil(len(string) / 2.0)
    toremove = len(string) - maxLength
    lstrip = math.ceil(toremove / 2.0)
    rstrip = toremove - lstrip
    lbound = int(midpoint - lstrip)
    rbound = int(midpoint + rstrip)
    return string[0:lbound] + '...' + string[rbound:]
    

#
# Time handling routines
#

# defines time format string for ISO-8601 datetimes
ISO_8601_STRFTIME = '%Y-%m-%dT%H:%M:%S%z'

# defines time format string for ISO-8601 datetimes, with a token for microsecond
# insertion by a second pass; see getIsoTime
ISO_8601_STRFTIME_MSECOND = '%Y-%m-%dT%H:%M:%S{msec}%z'

# defines canonical 0 time difference
ZEROTIME = timedelta(0)

# defines canonical 1 hour time difference
HOUR = timedelta(hours=1)

# define local non-DST offset
STDOFFSET = timedelta(seconds = -time.timezone)

# defin local DST offset
if time.daylight:
    DSTOFFSET = timedelta(seconds = -time.altzone)
else:
    DSTOFFSET = STDOFFSET

        
class UTCInfo(tzinfo):
    """
    Represents a UTC timezone. Use when a timezone-aware datetime() needs to be
    identified as a UTC time.

    Most invocations should use the singleton instance defined as splunk.util.utc
    """

    def utcoffset(self, dt):
        return ZEROTIME

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return ZEROTIME
utc = UTCInfo()



class LocalTZInfo(tzinfo):
    '''
    Represents the local server's idea of its native timezone. Use when creating
    a timezone-aware datetime() object.

    Most invocations should use the singleton instance defined as splunk.util.localTZ
    '''

    def utcoffset(self, dt):
        if self._isdst(dt):
            return DSTOFFSET
        else:
            return STDOFFSET

    def dst(self, dt):
        if self._isdst(dt):
            return DSTOFFSET - STDOFFSET
        else:
            return ZEROTIME

    def tzname(self, dt):
        return time.tzname[self._isdst(dt)]

    def _isdst(self, dt):
        try:
            tt = (dt.year, dt.month, dt.day,
                  dt.hour, dt.minute, dt.second,
                  dt.weekday(), 0, -1)
            stamp = time.mktime(tt)
            tt = time.localtime(stamp)
            return tt.tm_isdst > 0
        except:
            return False
localTZ = LocalTZInfo()


class TZInfo(tzinfo):
    """
    Represents a generic fixed offset timezone, as specified by 'offset' in
    minutes east of UTC (US is negative minutes).
    
    Setting offset=0 or None will result in a UTC-like timezone object that
    coerces an enclosing datetime()->time_struct with is_dst=-1.
    """

    def __init__(self, offset=None, name=''):
        if offset == None: 
            offset = int(getTimeOffset()/60)
        self.__offset = timedelta(minutes = offset)
        self.__name = name

    def utcoffset(self, dt):
        return self.__offset

    def tzname(self, dt):
        return self.__name

    def dst(self, dt):
        return ZEROTIME
        
    def __repr__(self):
        return '<TZinfo offset="%s" name="%s">' % (self.__offset, self.__name)
        
    
        
def getTimeOffset(t=None, dual_output=False):
    """Return offset of local zone from GMT in seconds, either at present or at time t."""
    # python2.3 localtime() can't take None
    if t is None:
        t = time.time()

    if not dual_output:
        if time.localtime(t).tm_isdst and time.daylight:
            return -time.altzone
        else:
            return -time.timezone
            
    return (-time.timezone, -time.altzone)
        
def format_local_tzoffset(t=None):
    '''
    Render the current process-local timezone offset in standard -0800 type
    format for the present or at time t.
    '''
    offset_secs = getTimeOffset(t)

    plus_minus = "+"
    if offset_secs < 0:
        plus_minus = '-'
    offset_secs = abs(offset_secs)

    hours, rem_secs  = divmod(offset_secs, 3600 )   # 60s * 60m -> hours
    minutes = (rem_secs / 60)
    return "%s%0.2i%0.2i" % (plus_minus, hours, minutes)


iso_re = None
offset_re = None
BYTE_PARSE_REX = None
compiled_regexes = False

def _compile_regexes():
    global compiled_regexes, iso_re, offset_re, BYTE_PARSE_REX
    if compiled_regexes:
       return    
    iso_re = re.compile(r'(\d{4})\-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.(\d{1,6}))?(z|Z|[\+\-]\d{2}\:?\d{2})?')
    offset_re = re.compile(r'([\+\-]?)(\d{2})\:?(\d{2})')
    BYTE_PARSE_REX = re.compile(r'(\-?[0-9\.]+)\s*([A-Za-z]{1,3})')
    compiled_regexes = True

def parseISO(timestamp, strict=False):
    '''
    Converts an ISO-8601 datetime string into a native python datetime.datetime
    object.  This only supports a strict well-formed time:

    Offset-explicit timezone:
    
        2005-07-01T00:00:00.000-07:00
        2005-07-01 00:00:00.000-07:00
        2005-07-01 00:00:00.000-0700

        The datetime object's tzinfo will be set to an instance of splunk.util.TZInfo()

    UTC timezone:

        2005-07-01T00:00:00.000Z
        2005-07-01T00:00:00.000+00:00

        The datetime object's tzinfo will be set to splunk.util.utc

    Local server timezone:

        2005-07-01T00:00:00.000

        The datetime object's tzinfo will be set to splunk.util.localTZ


    @param {Boolean} strict Indicates if an exception should be thrown if
        'timestamp' is not a valid ISO-8601 string
    '''
   
    _compile_regexes() 
    match = iso_re.search(timestamp)
    if match:
        
        year        = int(match.group(1))
        month       = int(match.group(2))
        day         = int(match.group(3))
        hour        = int(match.group(4))
        minute      = int(match.group(5))
        second      = int(match.group(6))
        
        msecond = 0
        if match.group(8):
            numtext = match.group(8)
            msecond = int(numtext)
            # if not microseconds, multiply by power to get number of microseconds
            if len(numtext) < 6:
                msecond *= math.pow(10, 6-len(numtext))
                msecond = int(msecond) # must be int

        tz = match.group(9)
        if tz in ('z','Z'):
            tzinfo = utc
        elif tz:
            tzinfo = TZInfo(parseISOOffset(tz), '')
        else:
            # set timezone as local server tz
            tzinfo = localTZ

        return datetime(year, month, day, hour, minute, second, msecond, tzinfo)
    
    else:
        if strict:
            raise ValueError, 'Cannot interpret value as ISO-8601: %s' % timestamp
        else:
            return datetime(1,1,1)
    

    
def parseISOOffset(offset):
    '''
    Converts a string ISO-8601 timezone offset literal into minutes.
    
    ex:
        -0700
        -07:00
        +00:00
        +10:26
    '''
    _compile_regexes() 
    match = offset_re.search(offset)
    if match:
        dir = int('%s1' % match.group(1))
        hours = int(match.group(2))
        minutes = int(match.group(3))
        return dir * ((hours * 60) + minutes)
        
    else:
        raise ValueError, "Unknown time offset value: %s" % offset
    
    
    
def getISOTime(ts=None):
    '''
    Returns an ISO-8601 formatted string that represents the timestamp.  ts can be
    a time struct or datetime() object.  If ts is a time.struct_time, then it is
    assumed to be in local time offset. If no value passed, then the current time
    is returned, in local time offset
    '''
    
    if isinstance(ts, datetime):
        if ts.microsecond:
            output = ts.strftime(ISO_8601_STRFTIME_MSECOND)
            output = output.replace('{msec}', '.%03d' % int(ts.microsecond/1000.0))
            return output
        else:
            return ts.strftime(ISO_8601_STRFTIME)
    
    elif isinstance(ts, time.struct_time):
        # first get offset of ts in local timezone
        offset = getTimeOffset(time.mktime(ts)) / 60
        dt = datetime(ts[0], ts[1], ts[2], ts[3], ts[4], ts[5], 0, TZInfo(offset))
        return dt.strftime(ISO_8601_STRFTIME)

    elif not ts:
        return datetime.now().strftime(ISO_8601_STRFTIME)

    else:
        raise ValueError, 'Unable to parse timestamp; not recognized as datetime object or time struct: %s' % ts
            
        
def mktimegm(tuple):
    """
    UTC version of time.mktime() written by Guido van Rossum
    """
    import calendar
    EPOCH = 1970
    year, month, day, hour, minute, second = tuple[:6]
    assert 1 <= month <= 12
    days = 365*(year-EPOCH) + calendar.leapdays(EPOCH, year)
    for i in range(1, month):
            days = days + calendar.mdays[i]
    if month > 2 and calendar.isleap(year):
            days = days + 1
    days = days + day - 1
    hours = days*24 + hour
    minutes = hours*60 + minute
    seconds = minutes*60 + second
    return seconds
    
def dt2epoch(datetime):
    '''
    Converts a datetime.datetime object into epoch time, with microsecond support
    '''
    
    if datetime == None:
        raise ValueError, 'Cannot convert empty value'
        
    basetime = mktimegm(datetime.utctimetuple())
    import decimal
    return decimal.Decimal('%s.%06d' % (basetime, datetime.microsecond))
    
    

def readSplunkFile(path):
    '''
    Returns a file that exists inside $SPLUNK_HOME.  All paths are homed at
    SPLUNK_HOME
    
    Ex:
    
        readSplunkFile('README.txt') ==> returns $SPLUNK_HOME/README.txt
        readSplunkFile('/README.txt') ==> returns $SPLUNK_HOME/README.txt
        readSplunkFile('etc/log.cfg') ==> returns $SPLUNK_HOME/etc/log.cfg
        
    TODO: this probably has some quirks in windows
    '''
    
    home = os.environ['SPLUNK_HOME']
    if not home or home == '/':
        raise Exception, 'readSplunkFile requires a SPLUNK_HOME to be set'
        
    workingPath = path.strip(os.sep)
    workingPath = os.path.join(home, workingPath)
    pathParts = os.path.split(workingPath)
    pathParts = filter(lambda x: x != os.pardir, pathParts)
    finalPath = os.path.join(*pathParts)
    fh = open(os.path.abspath(finalPath), 'r')
    try:
        output = fh.readlines()
        return output
    finally:
        if fh: fh.close()
        

    
class OrderedDict(UserDict, object):
    '''
    Provides a dictionary that respects the order in which items were inserted.
    Upon iteration or pop, items will be returned in the original order.
    
    The OrderedDict can be populated on instantiation by passing a list of 
    tuples, ex:
    
    OrderedDict([
        ('name', 'Name'),
        ('userid', "User ID"), 
        ('schedule', "Schedule"), 
        ('lastrun', 'Last Run On'),
        ('nextrun', 'Next Run At'),
        ('enableSched', "Enabled")
    ])
    '''
    
    def __init__(self, dict = None):
        self._keys = []
        if isinstance(dict, list):
            UserDict.__init__(self)
            for x in dict:
                self[x[0]] = x[1]
        else:
            UserDict.__init__(self, dict)

    def __delitem__(self, key):
        UserDict.__delitem__(self, key)
        self._keys.remove(key)

    def __setitem__(self, key, item):
        UserDict.__setitem__(self, key, item)
        if key not in self._keys: self._keys.append(key)

    def __iter__(self):
        return self._keys.__iter__()

    def iterKeys(self):
        return self._keys.__iter__()   
        
    def __str__(self):
        o = []
        for k in self:
            o.append("'%s': '%s'" % (k,self[k]))
        return '{' + ', '.join(o) + '}'
        
    def clear(self):
        UserDict.clear(self)
        self._keys = []

    def copy(self):
        dict = UserDict.copy(self)
        dict._keys = self._keys[:]
        return dict

    def items(self):
        return zip(self._keys, self.values())

    def keys(self):
        return self._keys

    def popitem(self, last=True):
        try:
            idx = -1
            if not last:
                idx = 0
            key = self._keys[idx]
        except IndexError:
            raise KeyError('dictionary is empty')

        val = self[key]
        del self[key]

        return (key, val)

    def setdefault(self, key, failobj = None):
        UserDict.setdefault(self, key, failobj)
        if key not in self._keys: self._keys.append(key)

    def update(self, dict):
        UserDict.update(self, dict)
        for key in dict.keys():
            if key not in self._keys: self._keys.append(key)

    def values(self):
        return map(self.get, self._keys)


def urlencodeDict(query):
    '''
    Convert a dictionary to a url-encoded" string.
    Multi-values keys can be assigned using a list (eg., {"foo": ["bar1", "bar2"]}.
    
    Note: None type values are removed.
    '''
    qargs = []
    [ qargs.extend([(k, e) for e in v]) for k,v in [ (k, v if isinstance(v, (list, tuple)) else (v,) ) for k, v in query.iteritems() if v != None ] ]
    return '&'.join( [ '%s=%s' % ( safeURLQuote(unicode(k)),safeURLQuote(unicode(v)) ) for k,v in qargs ] )


def toUnicode(obj, decodeFrom='utf-8'):
    '''
    Attempts to decode obj into a unicode object if obj is a str, 
    otherwise simply returns obj.

    Primarily used as a helper function in toUnicode.
    '''
    if isinstance(obj, basestring) and not isinstance(obj, unicode):
        return unicode(obj, decodeFrom)
        
    elif '__str__' in dir(obj):
        return unicode(obj)
        
    return obj


def toUTF8(obj, decodeFrom='utf-8', encodeTo='utf-8'):
    '''
    Attempts to return a utf-8 encoded str object if obj is an instance of basestring,
    otherwise just returns obj.
    
    Can be used to safely print out high byte unicode characters.
    Example:

    # This assumes the string entered is input in utf-8
    foo = u'KivimÃ¤ki2'
    urllib.quote(splunk.util.toUTF8(foo))
    '''
    if isinstance(obj, unicode):
        return obj.encode(encodeTo)

    elif isinstance(obj, str):
        return obj.decode(decodeFrom).encode(encodeTo)
        
    elif '__str__' in dir(obj):
        return toUTF8(unicode(obj))

    return obj


def objUnicode(obj, decodeFrom='utf-8', deep=True):
    '''
    Ensures all strings passed in are returned as unicode.
    Can handle strings in lists, dicts and tuples.
    By default does a deep traversal to convert all strings to unicode.

    Example:
    toUnicode({'one': 'one', {'two': 2, 'three': u'three', 'four': 'four'}})

    will return:
    {'one': u'one', {'two': 2, 'three': u'three', 'four', u'four'}}
    '''
    mapFunc = objUnicode
    if not deep: mapFunc = toUnicode

    if isinstance(obj, basestring):
        return toUnicode(obj, decodeFrom)

    elif isinstance(obj, list) or isinstance(obj, tuple):
        out = []
        if not deep:
            for item in obj:
                if not isinstance(item, basestring):
                    out.append(item)
                else:
                    out.append(mapFunc(item, decodeFrom))
            return obj.__class__(out)
        else:
            return obj.__class__([mapFunc(item, decodeFrom) for item in obj])

    elif isinstance(obj, dict) or isinstance(obj, UserDict):
        out = []
        if not deep:
            for key, value in obj.items():
                if not isinstance(value, basestring):
                    out.append((key, value))
                else:
                    out.append((key, mapFunc(value, decodeFrom)))
            return obj.__class__(out)
        else:
            return obj.__class__([(key, mapFunc(value, decodeFrom)) for key, value in obj.items()])

    return obj


def safeURLQuote(string, safe='/', decodeFrom='utf-8', encodeFrom='utf-8'):
    '''
    Safely encode high byte characters from unicode or
    some other encoding to UTF-8 url strings.

    For some reason urllib.quote can't handle high byte unicode strings,
    although urllib.unquote can unquote anything. Awesome.

    Always returns STR objects!
    '''
    return urllib.quote(toUTF8(string, decodeFrom, encodeFrom), safe)
    
    
def safeURLQuotePlus(string, safe='', decodeFrom='utf-8', encodeFrom='utf-8'):
    '''
    Safely encode high byte characters from unicode or other encodings
    to UTF-8 using the default HTML form encoding style where space is
    represented by a plus sign "+".
    '''
    return urllib.quote_plus(toUTF8(string, decodeFrom, encodeFrom), safe)
    

def setSSLWrapProtocol(ssl_protocol_version):
    """
    Sometimes we need to insist that outbound connections are made using
    SSL v3 rather than v2 or v3.
    urllib, httplib and httplib2 provide no easy way to do this so
    this function monkey patches ssl.wrap_socket to change the default
    protocol
    """
    import ssl
    def wrap_socket(sock, keyfile=None, certfile=None,
                    server_side=False, cert_reqs=ssl.CERT_NONE,
                    ssl_version=ssl_protocol_version, ca_certs=None,
                    do_handshake_on_connect=True,
                    suppress_ragged_eofs=True):

        return ssl.SSLSocket(sock, keyfile=keyfile, certfile=certfile,
                         server_side=server_side, cert_reqs=cert_reqs,
                         ssl_version=ssl_version, ca_certs=ca_certs,
                         do_handshake_on_connect=do_handshake_on_connect,
                         suppress_ragged_eofs=suppress_ragged_eofs)
    ssl.wrap_socket = wrap_socket



def isValidUnsignedFloat(x):
    try: 
        return float(x) >= 0
    except ValueError: 
        return False

def parseByteSizeString(input_string, base=2):
    '''
    Parses a string that identifies a byte size string.  Input values can be
    numeric with a suffix of the forms:

        B, KB, MB, ..., YB      (SI, binary)
           KiB, MiB, ..., YiB   (IEC)

    Values that do not have a suffix are assumed to be of units 'B'.

    The 'base' parameter can be specified what base to use when converting
    the input_string down to bytes.  This parameter is ignored if an IEC
    suffix is detected.  Defaults to 2.

    USAGE

        >>> parseByteSizeString('16MB')
        {
            'byte_value': 16777216,
            'relative_value': 16,
            'units': 'MB'
        }
    '''
    _compile_regexes() 
    match = BYTE_PARSE_REX.search(input_string)

    # if input is unqualified, assume to be bytes
    if match == None:
        try:
            byte_value = float(input_string)
        except:
            raise ValueError, 'cannot parse byte size string: %s' % input_string

        relative_value = byte_value
        units = 'B'

    # otherwise normalize as necessary
    else:
        relative_value = float(match.group(1))
        units = match.group(2)
    
        if units.upper().find('I') == 1:
            base = 2
        elif base not in (2, 10):
            raise ValueError, 'unsupported base: %s' % base
        
        # define the mapping from value magnitude to friendly suffix
        prefix_map = {
            'YIB': (80, 0), 
            'ZIB': (70, 0), 
            'EIB': (60, 0), 
            'PIB': (50, 0), 
            'TIB': (40, 0), 
            'GIB': (30, 0), 
            'MIB': (20, 0), 
            'KIB': (10, 0),
            'YB':  (80, 24), 
            'ZB':  (70, 21), 
            'EB':  (60, 18), 
            'PB':  (50, 15), 
            'TB':  (40, 12), 
            'GB':  (30,  9), 
            'MB':  (20,  6), 
            'KB':  (10,  3),
            'B':   ( 0,  0) 
        }
        map_index = 0 if base == 2 else 1

        try:
            adjustment_exponent = prefix_map[units.upper()][map_index]
        except:
            raise ValueError, 'unknown size prefix: %s' % units

        byte_value = (base ** adjustment_exponent) * relative_value

    return {
        'byte_value': byte_value,
        'relative_value': relative_value,
        'units': units
    }


def uuid4():
    """
    Generates version 4 uuid as specified in RFC 4122. See lib/python2.6/uuid.py.
    NOTE: Use this over uuid module as it's not shipped in our release.
    """
    # get randomness
    import random
    bytes = [chr(random.randrange(256)) for i in range(16)]
    int = long(('%02x'*16) % tuple(map(ord, bytes)), 16)
    # set variant to RFC 4122
    int &= ~(0xc000 << 48L)
    int |= 0x8000 << 48L
    # set version number
    int &= ~(0xf000 << 64L)
    int |= 4 << 76L
    hex = '%032x' % int
    return '%s-%s-%s-%s-%s' % (hex[:8], hex[8:12], hex[12:16], hex[16:20], hex[20:])


def splithost(hostport):
    """
    Split a host:port string into a (host, port) tuple
    Correctly splits [host]:port IPv6 addresses
    port is set to None if not present in the string
    """
    port = None
    if hostport.startswith('[') and hostport.find(']') > 0:
        host = hostport[1:hostport.find(']')]
        hostport = hostport[hostport.find(']') + 1:]
        if hostport.startswith(':'):
            port = int(hostport[1:])
    else:
        hostport = hostport.split(':', 1)
        if len(hostport) > 1:
            host = hostport[0]
            port = hostport[1]
        else:
            host = hostport[0]
    return (host, port)

def ensureCerts():
    """  
    if requireClientCert = false, return None/None; otherwise,
    ensure that the web.conf keyfile and certfile are present.
    If they are not, fall back to splunkweb fail-safe defaults,
    generating the certs if necessary (to help _http tests).
    """ 
    import splunk.clilib.cli_common as comm
  
    certfile = None 
    keyfile = None 

    # NOTE: use the cached merged instances of server/web.conf (in $SPLUNK_HOME/var/run/splunk/merged/)
    # they are regenerated everytime splunkweb is restarted. Spawning btool could take a long time !!!
    if normalizeBoolean(comm.getConfStanza('server', 'sslConfig').get('requireClientCert')):

        splunk_home = os.environ['SPLUNK_HOME']
        certfile = os.path.join(splunk_home, comm.getConfStanza('web', 'settings')['caCertPath'])
        keyfile = os.path.join(splunk_home, comm.getConfStanza('web', 'settings')['privKeyPath'])

        if not (os.path.exists(keyfile) or os.path.exists(certfile)):

            safe_path = os.path.join(splunk_home, 'etc', 'auth', 'splunkweb') 

            if not os.path.exists(safe_path):
                os.makedirs(safe_path, 0700)

            certfile = os.path.join(safe_path, 'cert.pem')
            keyfile = os.path.join(safe_path, 'privkey.pem')

            if not (os.path.exists(keyfile) and os.path.exists(certfile)):
                import shutil
                for file in [certfile, keyfile]:
                    if os.path.exists(file):
                        # prevent completely nuking a good cert
                        shutil.move(file, file + '.bak') 
     
                splunk_cmd = 'splunk'     
                if sys.platform.startswith('win'):
                    splunk_cmd = 'splunk.exe'

                # windows requires the fully qualified path to splunk
                splunk_bin = os.path.join(splunk_home, 'bin', splunk_cmd)

                try: 
                    subprocess.call([splunk_bin, 'createssl', 'web-cert'])
                except Exception, ex:  
                    raise

    return (keyfile, certfile)    


STRING_INTERPOLATION_RE_STRING="\$([^$]*)\$"
STRING_INTERPOLATION_RE=re.compile(STRING_INTERPOLATION_RE_STRING)

def interpolateString(template, dictionary):
    """ template is of form: 'blah blah $token1$ blah $token2$'
        dictionary is {'token1': 'Hello', 'token2': 'World'}
        result is: 'blah blah Hello blah World
    """
    result = template
    templateTokens = STRING_INTERPOLATION_RE.findall(template)
    for templateToken in templateTokens:
        if templateToken in dictionary:
            result = re.sub("\$%s\$" % templateToken, dictionary[templateToken], result)

    return result   

if __name__ == '__main__':
    
    import unittest

    class MainTest(unittest.TestCase):
        def test_interpolateString(self):
            self.assertEquals(interpolateString("$test$", {"test": "Hello World"}), "Hello World")
            self.assertEquals(interpolateString("$test1$ $test2$", {"test1": "Hello", "test2": "World"}), "Hello World")
            self.assertEquals(interpolateString("Hello $test$ World", {"test": "foobar", "test2": "blah"}), "Hello foobar World")
            self.assertEquals(interpolateString("Look$test$no$test2$", {"test": "ma", "test2": "spaces"}), "Lookmanospaces")
            self.assertEquals(interpolateString("$negativeTest$", {"test": "test"}), "$negativeTest$")    
 
        def test_parseByteSizeString(self):

            # spot check various units
            self.assertEquals(parseByteSizeString(
                '1B'), 
                {
                    'byte_value': 1,
                    'relative_value': 1,
                    'units': 'B'
                }
            )
            self.assertEquals(parseByteSizeString(
                '1MB'), 
                {
                    'byte_value': 1048576,
                    'relative_value': 1,
                    'units': 'MB'
                }
            )
            self.assertEquals(parseByteSizeString(
                '1TB'), 
                {
                    'byte_value': 1099511627776,
                    'relative_value': 1,
                    'units': 'TB'
                }
            )
            self.assertEquals(parseByteSizeString(
                '1YB'), 
                {
                    'byte_value': 1.2089258196146292e+24,
                    'relative_value': 1,
                    'units': 'YB'
                }
            )

            # check different numbers
            self.assertEquals(parseByteSizeString(
                '123456'), 
                {
                    'byte_value': 123456,
                    'relative_value': 123456,
                    'units': 'B'
                }
            )
            self.assertEquals(parseByteSizeString(
                '123456.789'), 
                {
                    'byte_value': 123456.789,
                    'relative_value': 123456.789,
                    'units': 'B'
                }
            )
            self.assertEquals(parseByteSizeString(
                '123.456GB'), 
                {
                    'byte_value': 132559870623.744,
                    'relative_value': 123.456,
                    'units': 'GB'
                }
            )
            self.assertEquals(parseByteSizeString(
                '-123.456GB'), 
                {
                    'byte_value': -132559870623.744,
                    'relative_value': -123.456,
                    'units': 'GB'
                }
            )
            self.assertEquals(parseByteSizeString(
                '0GB'), 
                {
                    'byte_value': 0,
                    'relative_value': 0,
                    'units': 'GB'
                }
            )

            # check IEC prefix
            self.assertEquals(parseByteSizeString(
                '-16MiB'), 
                {
                    'byte_value': -16777216,
                    'relative_value': -16,
                    'units': 'MiB'
                }
            )

            # check that base is ignored if IEC is detected
            self.assertEquals(parseByteSizeString(
                '16MiB', base=10), 
                {
                    'byte_value': 16777216,
                    'relative_value': 16,
                    'units': 'MiB'
                }
            )

            # check base awareness
            self.assertEquals(parseByteSizeString(
                '-16MB', base=10), 
                {
                    'byte_value': -16000000,
                    'relative_value': -16,
                    'units': 'MB'
                }
            )
            self.assertEquals(parseByteSizeString(
                '16MB', base=2), 
                {
                    'byte_value': 16777216,
                    'relative_value': 16,
                    'units': 'MB'
                }
            )
            self.assertEquals(parseByteSizeString(
                '0GB', base=10), 
                {
                    'byte_value': 0,
                    'relative_value': 0,
                    'units': 'GB'
                }
            )


        def testNormalizeBoolean(self):
            
            # test single string normalization
            self.assert_(normalizeBoolean(1) == True)
            self.assert_(normalizeBoolean('1') == True)
            self.assert_(normalizeBoolean('true') == True)
            self.assert_(normalizeBoolean('True') == True)
            self.assert_(normalizeBoolean('yes') == True)
            self.assert_(normalizeBoolean('y') == True)
            
            self.assert_(normalizeBoolean(0) == False)
            self.assert_(normalizeBoolean('0') == False)
            self.assert_(normalizeBoolean('false') == False)
            self.assert_(normalizeBoolean('False') == False)
            self.assert_(normalizeBoolean('no') == False)
            self.assert_(normalizeBoolean('n') == False)

            self.assert_(normalizeBoolean('') == '')
            self.assert_(normalizeBoolean('') != True)
            self.assert_(normalizeBoolean('') != False)
            self.assert_(normalizeBoolean(None) == None)

            self.assert_(normalizeBoolean(1, includeIntegers=False) == 1)
            self.assert_(normalizeBoolean('1', includeIntegers=False) == '1')
            self.assert_(isinstance(normalizeBoolean('1', includeIntegers=False), str))
            self.assert_(normalizeBoolean(0, includeIntegers=False) == 0)
            self.assert_(normalizeBoolean('0', includeIntegers=False) == '0')
            self.assert_(isinstance(normalizeBoolean('0', includeIntegers=False), str))
            
            self.assert_(normalizeBoolean('someother') == 'someother')
            
            self.assertRaises(ValueError, normalizeBoolean, 'someother', enableStrictMode=True)

            # test dictionary normalization
            testDictionary = {
            "lcT"   : "true",
            "ucT"   : "True",
            "lcF"   : "false",
            "ucF"   : "False",
            "numT"  : "1",
            "numF"  : "0",
            "ynT"   : "yes",
            "ynF"   : "no",
            "ynmT"  : "yEs",
            "ynmF"  : "nO",
            "ynsT"  : "y",
            "ynsF"  : "n",
            "ynsuT" : "Y",
            "ynsuF" : "N"
            }

            testDictionary_results = {
            "lcT"   : True,
            "ucT"   : True,
            "lcF"   : False,
            "ucF"   : False,
            "numT"  : True,
            "numF"  : False,
            "ynT"   : True,
            "ynF"   : False,
            "ynmT"  : True,
            "ynmF"  : False,
            "ynsT"  : True,
            "ynsF"  : False,
            "ynsuT" : True,
            "ynsuF" : False
            }

            for k in testDictionary:
                self.assert_( normalizeBoolean(testDictionary[k]) == testDictionary_results[k])
                self.assert_( normalizeBoolean(testDictionary[k]) != (not testDictionary_results[k]))
            
        
        def testParseISO(self):
            
            # test with T separator
            self.assertEqual(parseISO('2005-07-01T00:00:00.000-07:00'), datetime(2005,7,1,0,0,0,0,TZInfo(-7*60,'')))
            self.assertEqual(parseISO('2005-07-01T00:00:00.000-0700'), datetime(2005,7,1,0,0,0,0,TZInfo(-7*60,'')))
            self.assertEqual(parseISO('2005-07-01T00:00:00.000Z'), datetime(2005,7,1,0,0,0,0,utc))
            self.assertEqual(parseISO('2005-07-01T00:00:00.000'), datetime(2005,7,1,0,0,0,0,localTZ))

            # test with space separator
            self.assertEqual(parseISO('2005-07-01 00:00:00.000-07:00'), datetime(2005,7,1,0,0,0,0,TZInfo(-7*60,'')))
            self.assertEqual(parseISO('2005-07-01 00:00:00.000-0700'), datetime(2005,7,1,0,0,0,0,TZInfo(-7*60,'')))
            self.assertEqual(parseISO('2005-07-01 00:00:00.000Z'), datetime(2005,7,1,0,0,0,0,utc))
            self.assertEqual(parseISO('2005-07-01 00:00:00.000'), datetime(2005,7,1,0,0,0,0,localTZ))

            # test milliseconds
            self.assertEqual(parseISO('2005-07-01T13:45:57.000-07:00'), datetime(2005,7,1,13,45,57,0,TZInfo(-7*60,'')))
            self.assertEqual(parseISO('2005-07-01T13:45:57.334-07:00'), datetime(2005,7,1,13,45,57,334000,TZInfo(-7*60,'')))

            # test offsets with minutes defined
            self.assertEqual(parseISO('2005-07-01T00:00:00.000-07:45'), datetime(2005,7,1,0,0,0,0,TZInfo(-7*60-45,'')))
            self.assertEqual(parseISO('2005-07-01T00:00:00.000-0745'), datetime(2005,7,1,0,0,0,0,TZInfo(-7*60-45,'')))
            self.assertEqual(parseISO('2005-07-01T00:00:00.000+05:45'), datetime(2005,7,1,0,0,0,0,TZInfo(+5*60+45,'')))
            self.assertEqual(parseISO('2005-07-01T00:00:00.000+0545'), datetime(2005,7,1,0,0,0,0,TZInfo(+5*60+45,'')))
            
        def testParseISOTZLocal(self):
            '''check the timezone handling of parseISO in auto-set server locale'''

            # check DST of local server (assume US PDT locale)
            t = parseISO('2009-08-15T12:34:56.789')
            self.assertEquals(str(t), '2009-08-15 12:34:56.789000-07:00')
            
            t_utctuple = t.utctimetuple()
            self.assertEquals(t_utctuple.tm_year, 2009)
            self.assertEquals(t_utctuple.tm_mon, 8)
            self.assertEquals(t_utctuple.tm_mday, 15)
            self.assertEquals(t_utctuple.tm_hour, 19)
            self.assertEquals(t_utctuple.tm_min, 34)
            self.assertEquals(t_utctuple.tm_sec, 56)
            self.assertEquals(t_utctuple.tm_isdst, 0)

            t_localtuple = time.localtime(int(t.strftime('%s')))
            self.assertEquals(t_localtuple.tm_year, 2009)
            self.assertEquals(t_localtuple.tm_mon, 8)
            self.assertEquals(t_localtuple.tm_mday, 15)
            self.assertEquals(t_localtuple.tm_hour, 12)
            self.assertEquals(t_localtuple.tm_min, 34)
            self.assertEquals(t_localtuple.tm_sec, 56)
            self.assertEquals(t_localtuple.tm_isdst, 1)

            # check non-DST of local server (assume US PST locale)
            # should be 1 hour off, DST flag unset
            t = parseISO('2009-11-15T12:34:56.789')
            self.assertEquals(str(t), '2009-11-15 12:34:56.789000-08:00')

            t_utctuple = t.utctimetuple()
            self.assertEquals(t_utctuple.tm_year, 2009)
            self.assertEquals(t_utctuple.tm_mon, 11)
            self.assertEquals(t_utctuple.tm_mday, 15)
            self.assertEquals(t_utctuple.tm_hour, 20)
            self.assertEquals(t_utctuple.tm_min, 34)
            self.assertEquals(t_utctuple.tm_sec, 56)
            self.assertEquals(t_utctuple.tm_isdst, 0)
            
            t_localtuple = time.localtime(int(t.strftime('%s')))
            self.assertEquals(t_localtuple.tm_year, 2009)
            self.assertEquals(t_localtuple.tm_mon, 11)
            self.assertEquals(t_localtuple.tm_mday, 15)
            self.assertEquals(t_localtuple.tm_hour, 12)
            self.assertEquals(t_localtuple.tm_min, 34)
            self.assertEquals(t_localtuple.tm_sec, 56)
            self.assertEquals(t_localtuple.tm_isdst, 0)


        def testParseISOTZOffset(self):
            '''check the timezone handling of parseISO in fixed offset'''

            # check UTC normalization of fixed offset (while in DST zone)
            t = parseISO('2009-08-15T12:34:56.789-05:00')
            self.assertEquals(str(t), '2009-08-15 12:34:56.789000-05:00')
            t_tuple = t.utctimetuple()
            self.assertEquals(t_tuple.tm_year, 2009)
            self.assertEquals(t_tuple.tm_mon, 8)
            self.assertEquals(t_tuple.tm_mday, 15)
            self.assertEquals(t_tuple.tm_hour, 17)
            self.assertEquals(t_tuple.tm_min, 34)
            self.assertEquals(t_tuple.tm_sec, 56)
            self.assertEquals(t_tuple.tm_isdst, 0)


            # check UTC normalization of fixed offset (while outside of DST zone)
            # should be same as above
            t = parseISO('2009-11-15T12:34:56.789-05:00')
            self.assertEquals(str(t), '2009-11-15 12:34:56.789000-05:00')
            t_tuple = t.utctimetuple()
            self.assertEquals(t_tuple.tm_year, 2009)
            self.assertEquals(t_tuple.tm_mon,11)
            self.assertEquals(t_tuple.tm_mday, 15)
            self.assertEquals(t_tuple.tm_hour, 17)
            self.assertEquals(t_tuple.tm_min, 34)
            self.assertEquals(t_tuple.tm_sec, 56)
            self.assertEquals(t_tuple.tm_isdst, 0)


        def testParseISOTZUTC(self):
            '''check the timezone handline of parseISO in UTC'''

            # check UTC normalization of fixed offset (while in DST zone)
            t = parseISO('2009-08-15T12:34:56.789z')
            self.assertEquals(str(t), '2009-08-15 12:34:56.789000+00:00')
            t_tuple = t.utctimetuple()
            self.assertEquals(t_tuple.tm_year, 2009)
            self.assertEquals(t_tuple.tm_mon, 8)
            self.assertEquals(t_tuple.tm_mday, 15)
            self.assertEquals(t_tuple.tm_hour, 12)
            self.assertEquals(t_tuple.tm_min, 34)
            self.assertEquals(t_tuple.tm_sec, 56)
            self.assertEquals(t_tuple.tm_isdst, 0)


            # check UTC normalization of fixed offset (while outside of DST zone)
            # should be the same as above
            t = parseISO('2009-11-15T12:34:56.789Z')
            self.assertEquals(str(t), '2009-11-15 12:34:56.789000+00:00')
            t_tuple = t.utctimetuple()
            self.assertEquals(t_tuple.tm_year, 2009)
            self.assertEquals(t_tuple.tm_mon,11)
            self.assertEquals(t_tuple.tm_mday, 15)
            self.assertEquals(t_tuple.tm_hour, 12)
            self.assertEquals(t_tuple.tm_min, 34)
            self.assertEquals(t_tuple.tm_sec, 56)
            self.assertEquals(t_tuple.tm_isdst, 0)


        def testEpoch(self):
            import decimal
            
            # check rounding errors
            for ts in [
                -1,
                0,
                1205775389,
                '1205775389',
                '1205775389.1', 
                '1205775389.12', # compare to float(1205775389.12) ==> 1205775389.1199999
                '1205775389.123', 
                '1205775389.1234', 
                '1205775389.12345', 
                '1205775389.123456', 
                '1205775389.9', 
                '1205775389.99', 
                '1205775389.999', 
                '1205775389.9999', 
                '1205775389.99999', 
                '1205775389.999999',
                '1205775389.9', 
                '1205775389.09', 
                '1205775389.009', 
                '1205775389.0009', 
                '1205775389.00009', 
                '1205775389.000009'
                ]:
                ts = decimal.Decimal(ts)
                dt = datetime.utcfromtimestamp(ts)
                self.assertEqual(dt2epoch(dt), ts)
            
            # check expected rounding; datetime object is limited to microseconds
            dt = datetime.utcfromtimestamp(decimal.Decimal('1205883921.1234567'))
            self.assertEqual(dt2epoch(dt), decimal.Decimal('1205883921.123457'))
            
            # check null handling
            self.assertRaises(ValueError, dt2epoch, None)


        def testOrderedDict(self):
            '''
            test the ordered dictionary
            '''

            od = OrderedDict()

            keys = 'abcdefghijklmnopqrstuvwxyz'
            KEYS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

            keysd = []
            for char in keys:
                od[char] = 'foo'
                keysd.append(char)

            for i, k in enumerate(od):
                self.assertEquals(k, keys[i])
                
            for i in range(-1,-5,-1):
                self.assertEquals(keys[i], od.popitem()[0])
            
            KEYSd = []    
            for char in KEYS:
                od[char] = 'bar'
                KEYSd.append(char)
                
            combined = keysd[0:-4] + KEYSd
            for i, k in enumerate(od):
                self.assertEquals(combined[i], k)
                    

        def testGetIsoTime(self):
            
            self.assertEqual(
                getISOTime(datetime(2005,7,1,0,0,0,2000,TZInfo(-7*60,''))), 
                '2005-07-01T00:00:00.002-0700')

            self.assertEqual(
                getISOTime(datetime(2005,7,1,0,0,0,0,TZInfo(-7*60,''))), 
                '2005-07-01T00:00:00-0700')

            self.assertEqual(
                getISOTime(datetime(2005,7,1,0,0,0,5,TZInfo(-7*60,''))), 
                '2005-07-01T00:00:00.000-0700')

            self.assertEqual(
                getISOTime(datetime(2005,7,1,0,0,0,0,TZInfo(-7*60,''))), 
                '2005-07-01T00:00:00-0700')
            
            self.assertEqual(
                getISOTime(time.struct_time((2008, 9, 26, 21, 49, 50, 4, 270, 0))),
                '2008-09-26T21:49:50-0700')


        def assertQueryArgsEqual(self, queryStringOne, queryStringTwo):
            """ assert that the two query strings contain the exact same
                set of query args, regardless of order """
            queryStringOneParts = queryStringOne.split("&")
            queryStringTwoParts = queryStringTwo.split("&")
            self.assertItemsEqual(queryStringOneParts, queryStringTwoParts)        

        def testUrlencodeDict(self):
            self.assertQueryArgsEqual(
                urlencodeDict({'foo':'bar'}),
                'foo=bar'
            )
            
            self.assertQueryArgsEqual(
                urlencodeDict({'foo':'bar1 bar2'}),
                'foo=bar1%20bar2'
            )

            self.assertQueryArgsEqual(
                urlencodeDict({'foo1':'bar1', 'foo2':'bar2'}),
                'foo1=bar1&foo2=bar2'
            )

            self.assertQueryArgsEqual(
                urlencodeDict({'foo1':'bar1a bar1b', 'foo2':'bar2'}),
                'foo1=bar1a%20bar1b&foo2=bar2'
            )

            self.assertQueryArgsEqual(
                urlencodeDict({'foo':['bar1', 'bar2']}),
                'foo=bar1&foo=bar2'
            )
            
            self.assertQueryArgsEqual(
                urlencodeDict({'foo':['bar1a bar1b', 'bar2']}),
                'foo=bar1a%20bar1b&foo=bar2'
            )

            self.assertQueryArgsEqual(
                urlencodeDict({'foo':['bar1', 'bar2'], 'needle':'haystack'}),
                'needle=haystack&foo=bar1&foo=bar2'
            )

            self.assertQueryArgsEqual(
                urlencodeDict({'foo':['bar1', 'bar2'], 'needle':'haystack1 haystack2'}),
                'needle=haystack1%20haystack2&foo=bar1&foo=bar2'
            )
            
            self.assertQueryArgsEqual(
                urlencodeDict({'needle':'haystack', 'foo':['bar1', 'bar2']}),
                'needle=haystack&foo=bar1&foo=bar2'
            )
            
            self.assertQueryArgsEqual(
                urlencodeDict({'needle':'haystack1 haystack2', 'foo':['bar1', 'bar2']}),
                'needle=haystack1%20haystack2&foo=bar1&foo=bar2'
            )

            self.assertQueryArgsEqual(
                urlencodeDict({'needle1':'haystack1', 'foo':['bar1', 'bar2'], 'needle2':'haystack2'}),
                'needle1=haystack1&needle2=haystack2&foo=bar1&foo=bar2'
            )
            
            self.assertQueryArgsEqual(
                urlencodeDict({'needle1':'haystack1', 'foo':['bar1', 'bar2'], 'needle2':'haystack2a haystack2b'}),
                'needle1=haystack1&needle2=haystack2a%20haystack2b&foo=bar1&foo=bar2'
            )

        def assertUnicode(self, string):
            self.assertEquals(type(string), unicode, 'String should be unicode')

        def test_string_to_unicode_simple(self):
            self.assertUnicode(objUnicode('foo'))
            self.assertUnicode(objUnicode(u'foo'))

        def test_string_to_unicode_iter(self):
            listStrs = ['one', 'two', u'three', u'KivimÃ¤ki2', 'KivimÃ¤ki2', 4, ['notUnicode']]
            listStrsOut = objUnicode(listStrs, deep=False)
            foundNum = False
            for string in listStrsOut:
                if isinstance(string, basestring):
                    self.assertUnicode(string)
                if type(string) == int:
                    foundNum = True
            self.assertEquals(type(listStrsOut[6]), list, 'Should not convert second order objects.')
            self.assertEquals(type(listStrsOut[6][0]), str, 'Second order objects should preserve their internal str objs.')
            self.assert_(foundNum, 'Should not convert integers.')
            
            dictStrs = {'one': u'one', 'two': 'KivimÃ¤ki2', 'three': 3, 'four': {'first': 'bar'}}
            dictStrsOut = objUnicode(dictStrs, deep=False)
            foundNum = False
            for key in dictStrsOut:
                if isinstance(dictStrsOut[key], basestring):
                    self.assertUnicode(dictStrsOut[key])
                if type(dictStrsOut[key]) == int:
                    foundNum = True
            self.assertEquals(type(dictStrsOut['four']['first']), str, 'Should not convert second order objects.')
            self.assert_(foundNum, 'Should not convert integers.')

        def test_string_to_unicode_preserve_tuples(self):
            listWithTuples = ['one', 'two', ('tup', 'tup', ('duptup', 'duptup'))]
            listWithTuplesOut = objUnicode(listWithTuples)
            self.assertUnicode(listWithTuplesOut[0])
            self.assertUnicode(listWithTuplesOut[2][0])
            self.assertUnicode(listWithTuplesOut[2][1])
            self.assertUnicode(listWithTuplesOut[2][2][1])
            self.assertEquals(type(listWithTuplesOut[2]), tuple, 'Should preserve tuples')
            self.assertEquals(type(listWithTuplesOut[2][2]), tuple, 'Should preserve tuples')

        def test_string_to_unicode_depth_checks(self):
            deepList = ['one', ['two', 'KivimÃ¤ki2', ['level3', 5]]]
            deepListOut = objUnicode(deepList)
            self.assertUnicode(deepListOut[0])
            self.assertUnicode(deepListOut[1][0])
            self.assertUnicode(deepListOut[1][1])
            self.assertUnicode(deepListOut[1][2][0])
            self.assert_(type(deepListOut[1][2][1]) == int)

            anotherDict = {'one': 'one', 'two': {'two_d': 2, 'three_d': u'three', 'four_d': 'four'}, 'uni': 'KivimÃ¤ki2'}
            anotherDictOut = objUnicode(anotherDict)
            self.assertUnicode(anotherDictOut['one'])
            self.assertUnicode(anotherDictOut['two']['three_d'])
            self.assertUnicode(anotherDictOut['two']['four_d'])
            self.assertUnicode(anotherDictOut['uni'])
            self.assert_(type(anotherDictOut['two']['two_d']) == int, 'Should not convert intergers.')

        def test_string_to_unicode_in_objects_like_dicts(self):
            origin = [('one', 'one'), ('two', 'two')]
            ordered = OrderedDict(origin)
            orderedOut = objUnicode(ordered)
            self.assert_((ordered is not orderedOut), 'objUnicode should return new objects.')
            for idx, key in enumerate(orderedOut):
                self.assertEquals(key, origin[idx][0], 'objUnicode should preserve order when its important')
                self.assertUnicode(orderedOut[key])

        def test_toUTF8(self):
            test_str = 'KivimÃ¤ki2'
            test_unicode = u'KivimÃ¤ki2'

            str_to_utf8 = toUTF8(test_str)
            unicode_to_utf8 = toUTF8(test_unicode)

            self.assertEquals(type(str_to_utf8), str, 'toUTF8 should always return a string.')
            self.assertEquals(type(unicode_to_utf8), str, 'toUTF8 should always return a string.')
            self.assertEquals(str_to_utf8, unicode_to_utf8, 'The output of toUTF8 should be consistent.')

        def test_safeURLQuote(self):
            test_st = 'KivimÃ¤ki2'
            test_unicode = u'KivimÃ¤ki2'

            self.assertEquals(type(safeURLQuote(test_st)), str, 'safeURLQuote always returns strings.')
            self.assertEquals(type(safeURLQuote(test_unicode)), str, 'safeURLQuote always returns strings.')

            test_st_unquote = urllib.unquote(safeURLQuote(test_st))
            self.assertEquals(test_st, test_st_unquote, 'strings passed through safeURLQuote and urllib.unquote should be equal to their str equivalent.')



        def test_stringToFieldList(self):
            field_list_cases = [
                [None, []],
                ['', []],
                ['one_field', ['one_field']],
                [' one_field', ['one_field']],
                [' one_field ', ['one_field']],
                ['a, b, c', ['a','b','c']],
                ['a b c', ['a','b','c']],
                ['a,b,c', ['a','b','c']],
                ['a   b,c', ['a','b','c']],
                ['one\\ two\\', ["one\\", "two\\"]],
                ['one \\\\', ["one", "\\"]],
                ["one \\\\\ \ ", ["one", "\\\\", "\\"]],
                ["one,\\", ["one", "\\"]],
                ['_raw,foo \\ bar, "baz \\', ['_raw', 'foo', '\\', 'bar', 'baz \\']],
                ['one,two,three"', ["one", "two", "three"]],
                ['one,"\\\\",two', ["one", "\\", "two"]],
                ['one,"\\\\","two\\\\three\\\\four"', ["one", "\\", "two\\three\\four"]],

                ['_raw,"first \\\\ ip","\\"weird quoted string\\"","random\\"quote"', ["_raw", "first \\ ip", '"weird quoted string"', 'random"quote']]
            ]

            for pair in field_list_cases:
                self.assertEquals(stringToFieldList(pair[0]), pair[1])
                

        def test_fieldListToString(self):
            field_list_cases = [
                ['', []],
                ['one_field', ['one_field']],
                ['a,b,c', ['a','b','c']],
                ['a,"foo\\\\bar",c', ['a','foo\\bar','c']],
                ['a,b,c,"d,e"', ['a','b','c','d,e']],
                ['"one\\\\",two', ["one\\", "two"]],
                ['_raw,foo,"\\\\",bar,"baz \\\\"', ['_raw', 'foo', '\\', 'bar', 'baz \\']],
                ['one,"\\\\",two', ["one", "\\", "two"]],
                ['one,"\\\\","two\\\\three\\\\four"', ["one", "\\", "two\\three\\four"]],
                ['"one\\\\",two,three,\'four,\'and\',not,"five\'\\\\","\\\\","six\\\\"', ["one\\", "two", "three", "'four", "'and'", "not", "five'\\", "\\", "six\\"]],

                # Test what we give is what we get
                ['_raw,"first \\\\ ip","\\"weird quoted string\\"","random\\"quote"', ["_raw", "first \ ip", '"weird quoted string"', 'random"quote']]
            ]
            for pair in field_list_cases:
                self.assertEquals(fieldListToString(pair[1]), pair[0])
            
        def test_smartTrim(self):
            
            s = '1234567890';

            self.assertEquals(smartTrim('', 23), '');
            self.assertEquals(smartTrim(None, 23), None);
            self.assertEquals(smartTrim(s, -1), '1234567890');
            self.assertEquals(smartTrim(s, 0), '1234567890');
            self.assertEquals(smartTrim(s, 1), '1...');
            self.assertEquals(smartTrim(s, 2), '1...0');
            self.assertEquals(smartTrim(s, 3), '1...90');
            self.assertEquals(smartTrim(s, 4), '12...90');
            self.assertEquals(smartTrim(s, 5), '12...890');
            self.assertEquals(smartTrim(s, 6), '123...890');
            self.assertEquals(smartTrim(s, 7), '123...7890');
            self.assertEquals(smartTrim(s, 8), '1234...7890');
            self.assertEquals(smartTrim(s, 9), '1234...67890');
            self.assertEquals(smartTrim(s, 10), '1234567890');
            self.assertEquals(smartTrim(s, 11), '1234567890');

        def test_fieldListToString_with_high_bytes(self):
            l = ['KivimÃ¤ki2', u'KivimÃ¤ki2', 'alsonotunicode', u'should be unicode']
            expect = u'KivimÃ¤ki2,KivimÃ¤ki2,alsonotunicode,"should be unicode"'
            found = fieldListToString(l)
            self.assertEquals(found, expect, "Failure:\n%s expected\n%s found" % (expect, found))
            self.assertEquals(type(found), type(expect), "Failure:\n%s expected\n%s found" % (type(expect), type(found)))
            
        
        def test_uuid4(self):
            uuids = []
            for i in range(0, 1000):
                uuid = uuid4()
                self.assertEquals(uuids.count(uuid), 0, "Same uuid generated, not unique.")
                uuids.append(uuid)
                
    # run tests
    suite = unittest.TestLoader().loadTestsFromTestCase(MainTest)
    unittest.TextTestRunner(verbosity=2).run(suite)
