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

class DataType(object):
 """
 Class to represent the data types of the properties.
 Each returned Property object has a data_type() method.
 """

 BOOLEAN = 0
 BYTE = 1
 SHORT = 2
 INTEGER = 3
 LONG =   4
 FLOAT   =   5
 DOUBLE  =   6
 STRING  =   7
 UNKNOWN =   8

 __names = {
  BOOLEAN:'Boolean',
  BYTE:   'Byte',
  SHORT:  'Short',
  INTEGER:'Integer',
  LONG:   'Long',
  FLOAT:  'Float',
  DOUBLE: 'Double',
  STRING: 'String',
  UNKNOWN:'Unknown'
 }

 @staticmethod
 def name(data_type_id):
  if data_type_id in DataType.__names:
   return DataType.__names[data_type_id]
  return None
