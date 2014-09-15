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

from mobi.mtld.da.data_type import DataType

class PropertyName(object):
 """
 Contains a property name and the expected data type of values associated with
 this name.
 """

 __name = ''
 __data_type_id = 0

 def __init__(self, name, data_type_id):
  """
  Create a new PropertyName with a name and the expected data type of
  value assigned to it.
  """
  if type(name) == str:
   self.__name = name
  else:
   self.__name = name.decode("utf-8")
  self.__data_type_id = data_type_id

 @property
 def name(self):
  return self.__name

 @property
 def data_type_id(self):
  return self.__data_type_id

 def data_type(self):
  """
  Get the data type name of this PropertyName object.
  """
  return DataType.name(self.__data_type_id)

 def str(self):
  """
  Returns the property data type id wrapped by breaks.
  """
  return "(%s)" % self.__data_type_id

 def __eq__(self, o):
  if isinstance(o, PropertyName):
   return (self.__name == o.__name and self.__data_type_id == o.__data_type_id)
  return False

 def __ne__(self, o):
  if isinstance(o, PropertyName):
   return (self.__name != o.__name or self.__data_type_id != o.__data_type_id)
  return True
