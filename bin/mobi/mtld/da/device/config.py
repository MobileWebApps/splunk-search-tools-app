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

class Config(object):

 # To change the cookie name that the client side properties would be set to.
 # When using DeviceApi.properties() on a Rails project, the detection would
 # automatically use the contents of this cookie if it exists.
 # If you want the client side properties to be used add the DeviceAtlas
 # client side component (JS lib) to your web-site pages.
 cookie_name = 'DAPROPS'

 # To disable or enable DeviceApi.properties including User-Agent
 # dynamic properties. Some properties cannot be known before runtime and can
 # change from User-Agent to User-Agent. The most common of these are the OS
 # Version and the Browser Version. The DeviceApi is able to dynamically detect
 # these changing properties with a small overhead. If you do not use this
 # properties you can set this config to false to make the detection a little
 # bit faster.
 include_ua_props = True

 # To check the Accept-Language header and include properties to the
 # property set for getting client's language and locale preferences set to
 # true. If you do not use this properties you can set this config to false to
 # make the detection marginally faster.
 include_lang_props = True

 # To include the matched and unmatched parts of the User-Agent to the property
 # set.
 include_match_info = False

 # The default config value for DeviceApi.properties when there are no
 # properties.
 # true = if we want to return nil when there are no properties,
 # false = if we want to return an instance of Properties without Property in
 return_none_when_no_properties = False
