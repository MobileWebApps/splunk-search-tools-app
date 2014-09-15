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

class DeviceAtlasException(Exception):
 """
 Superclass representing the base of the exception hierarchy.
 It makes our exceptions compatible with Python 3.
 """

 message = ""

 def __init__(self, message):
  """
  Constructor to provide the "message" attribute in Python 3.
  """
  self.message = message

 def __str__(self):
  return self.message
