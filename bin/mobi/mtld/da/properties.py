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

class Properties(dict):
 """
 Contains a hash of names to Property objects. An instance of this class is
 returned by DeviceApi.properties.
 """

 def contains(self, property_name, value_to_check):
  """
  Checks whether the properties set has the given pair of property and value.
  @param property_name: is a String with the property name.
  @param value_to_check: is a Value to check.
  It returs a bool value.
  """

  if property_name is None or value_to_check is None:
   return False

  if property_name in self:

   if self[property_name].value == value_to_check:
    return True

   if self[property_name].data_type_id == DataType.BOOLEAN:

    if (value_to_check == 'true' or value_to_check == 1 or
     value_to_check == '1' or value_to_check == True):
     return bool(self[property_name]) == True

    if (value_to_check == 'false' or value_to_check == 0 or
     value_to_check == '0' or value_to_check == False):
     return bool(self[property_name]) == False

   if self[property_name].data_type_id == DataType.INTEGER:
    try:
     value_to_check_int = int(value_to_check)
     return int(self[property_name]) == value_to_check_int
    except:
     return False

  return False

 def get(self, property_name):
  """
  Gets the value of the given property identified by its name.
  @param property_name: is a String with the property_name.
  It returns  Property value or None if the property does not exist.
  """
  if property_name in self:
   return self[property_name]
  return None
