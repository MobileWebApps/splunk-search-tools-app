#!/usr/bin/env python

"""
@copyright:
 Copyright (c) 2014 by mTLD Top Level Domain Limited. All rights reserved.\n
 Portions copyright (c) 2008 by Argo Interactive Limited.\n
 Portions copyright (c) 2008 by Nokia Inc.\n
 Portions copyright (c) 2008 by Telecom Italia Mobile S.p.A.\n
 Portions copyright (c) 2008 by Volantis Systems Limited.\n
 Portions copyright (c) 2002-2008 by Andreas Staeding.\n
 Portions copyright (c) 2008 by Zandan.\n
@author: dotMobi
"""

from mobi.mtld.da.exception.incorrect_property_type_exception import IncorrectPropertyTypeException
from mobi.mtld.da.data_type import DataType

class Property(object):
 """
 Contains a property value and data type id. The value can be fetched as a
 generic Object or one of the convenience str(), int(), bool() methods can be
 used to get the value in a specific type.
 """

 __value = ''
 __data_type_id = 0
 __data_type_name = 'Boolean'
 
 def __init__(self, value, data_type):
  """
  Creates a new Property with a value and data type
  @param value: is the value to store
  @param data_type: is a byte or char that represents the data type of the value to
  store
  """  
  if isinstance(data_type, basestring):

   if data_type == 'b':
    self.__data_type_id = DataType.BOOLEAN
    self.__value = value
   elif data_type == 'i':
    self.__data_type_id = DataType.INTEGER
    self.__value = int(value)
   elif data_type == 's':
    self.__data_type_id = DataType.STRING
    if isinstance(value, list):
     self.__value = ",".join(value)
    else:
     self.__value = str(value)
   elif data_type == 'd':
    self.__data_type_id = DataType.DOUBLE
    self.__value = value
   else:
    self.__data_type_id = DataType.UNKNOWN
    self.__value = value

  elif isinstance(data_type, int):

   self.__data_type_id = data_type
   
   if data_type == DataType.BOOLEAN:
    self.__value = value
   elif data_type == DataType.INTEGER:
    self.__value = int(value)
   elif data_type == DataType.STRING:
    if isinstance(value, list):
     self.__value = ",".join(value)
    else:
     self.__value = str(value)
   elif data_type == DataType.DOUBLE:
    self.__value = value
   else:
    self.__data_type_id = DataType.UNKNOWN
    self.__value = value

  self.__data_type_name = DataType.name(self.__data_type_id)

 @property
 def value(self):
  return self.__value

 @property
 def data_type_id(self):
  return self.__data_type_id

 def data_type(self):
  """
  Get data type name.
  It returns a String with the data type name
  """
  return self.__data_type_name

 def __iter__(self):
  """
  Gets a set of possible values for this property. This is typically only
  used when it is known that a given property name can have multiple
  possible values. All items in the set will have the same data type.
  It returns the array value of the property
  """
  if isinstance(self.__value, basestring) and self.__value.contains(","):
   values = self.__value.split(",")
  else:
   values = self.__value

  class iterator(object):
   def __init__(self, obj):
    self.obj = obj
    self.index = -1
   def __iter__(self):
    return self
   def next(self):
    if self.index < len(values) - 1:
     self.index += 1
     return self.obj[self.index]
    else:
     raise StopIteration
  return iterator(self.__value)


 def __bool__(self):
  """
  Get the value of the property as a boolean (Python 3.x)
  """
  return self.__nonzero__()

 def __nonzero__(self): # Python 2.x

  if(self.__data_type_id != DataType.BOOLEAN):
   raise IncorrectPropertyTypeException('Property is not convertible to a ' +
    'boolean')

  return self.__value == 1 or self.__value == '1' or self.__value is True

 def __int__(self):
  """
  Get the value of the property as an integer.
  """
  if(self.__data_type_id != DataType.BYTE and
  self.__data_type_id != DataType.SHORT and
  self.__data_type_id != DataType.INTEGER):
   raise IncorrectPropertyTypeException('Property is not convertible to an int')

  return int(self.__value)

 def __str__(self):
  """
  Gets the value of the property as string. If a property has multiple possible
  values then the values are concatenated with a comma.
  """
  if isinstance(self.__value, list):
   for i in range(0, len(self.__value)):
    if isinstance(self.__value[i], bytes):
     self.__value[i] = self.__value[i].decode("utf-8")
   return ",".join(self.__value)

  if isinstance(self.__value, bytes):
   try:
    self.__value = self.__value.decode("utf-8")
   except:
    pass

  return str(self.__value)

 def __eq__(self, other):
  """
  Compare two instances of this class.
  If both have equal values and data type then returns true.
  """
  return (type(self) == type(other) and
  self.data_typeName == other.data_type() and
  self.__value == other.value)

 def __ne__(self, other):
  """
  Opposite to __eq__()
  """
  return (type(self) != type(other) or
  self.data_typeName != other.data_type() or
  self.__value != other.value)
