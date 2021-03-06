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

from mobi.mtld.da.exception.device_atlas_exception import DeviceAtlasException

class IncorrectPropertyTypeException(DeviceAtlasException):
 """
 IncorrectPropertyTypeException is thrown when there is an attempt to fetch a
 property by type and the property is stored under a different type in the
 tree.
 """
 pass
