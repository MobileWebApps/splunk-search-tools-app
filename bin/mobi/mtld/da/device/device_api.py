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

import os.path

from mobi.mtld.da.exception.data_file_exception import DataFileException
from mobi.mtld.da.device.tree import Tree
from mobi.mtld.da.device.config import Config
from mobi.mtld.da.property_name import PropertyName
from mobi.mtld.da.data_type import DataType
from mobi.mtld.da.property import Property


class DeviceApi(object):
 """
 The DeviceAtlas Device Detection API provides a way to detect devices based on
 the HTTP headers. Using the headers, the API returns device information such
 as screen width, screen height, is mobile, vendor, model etc.

 DeviceApi.get_properties(user_agent_or_headers, client_side_properties)

 To get the most accurate results:
 1- Pass the whole HTTP headers.
 2- Use the DeviceAtlas client-side-component and pass the result.

 Example usage:

 >>> device_api = DeviceApi()
 >>> device_api.load_data_from_file("/path/to/datafile.json")
 >>>
 >>> # get all properties from the headers
 >>> properties = device_api.get_properties(headers)
 >>>
 >>> # .... use the properties ....
 >>>
 >>> if properties.contains("isMobilePhone", True):
 >>>  # it is a mobile phone
 >>>
 >>> if "model" in properties:
 >>>  device_model = str(properties.get("model"))
 """

 api_version = '2.0'

 __config = None
 __tree = None
 __cached_client_side_properties = None
 __cached_user_agent = None
 __cached_headers = None
 __properties = None

 def __init__(self, config = None):
  """
  Constructs a DeviceApi instance with default configs. You can see the
  default configs in the class "Configuration".

  @param config: Instance of Configuration. You can change the DeviceAtlas API
  configs by creating an instance or Configuration and setting your custom
  config values then passing the instance to the DeviceApi constructor.
  """
  if config is None:
   self.__config = Config()
  else:
   self.__config = config

 def load_data_from_file(self, json_data_file_path):
  """
  Load the DeviceAtlas device detection data into the API from a JSON file.
  The JSON data file is provided from the DeviceAtlas web-site.
  @param json_data_file_path: Path to the JSON data file.
  """

  if not os.path.isfile(json_data_file_path):
   raise DataFileException("File not found: " + json_data_file_path)

  json = open(json_data_file_path, 'r').read()

  self.load_data_from_string(json)

 def load_data_from_string(self, json_data_string):
  """
  Load the DeviceAtlas device detection data into the API from a string.
  @param json_data_string: JSON data string.
  """
  self.__tree = None
  self.__tree = Tree(json_data_string, self.__config)

 def get_property_names(self):
  """
  Get a set of available device property names.
  It returns a list of PropertyName objects.
  """
  property_names = []
  property_type_names = self.__tree.property_names()
  for property_type_name in property_type_names:
   property_names.append(
    PropertyName(
     property_type_name[1:len(property_type_name)],
     self.__get_property_as_byte(
      property_type_name[0])))
  return property_names

 def get_data_version(self):
  """
  Get the device data (JSON file) version.
  """
  return self.__tree.data_version()

 def get_data_revision(self):
  """
  Get the device data (JSON file) revision.
  """
  return self.__tree.data_revision

 def get_data_creation_timestamp(self):
  """
  Get the device data (JSON file) creation timestamp.
  """
  return self.__tree.data_creation_timestamp()

 def get_properties(self, user_agent_or_headers, client_side_properties = None):
  """
  Get known properties from a User-Agent or HTTP headers optionally
  merged with properties from the client side component.
  The client side component (JS) sets a cookie with collected properties.
  The client properties will over-ride any properties discovered from the main
  JSON data file.

  @param user_agent_or_headers: User-Agent string or array of HTTP headers.
  @param client_side_properties: String of client side properties with the format
  the client side component provides.
  It returns a list of Property objects
  """
  new_cached_client_side_properties = False

  if (client_side_properties is None or
     self.__cached_client_side_properties != client_side_properties):

   self.__cached_client_side_properties = client_side_properties
   new_cached_client_side_properties = True

  # Just a UA
  if (isinstance(user_agent_or_headers, str) or
      isinstance(user_agent_or_headers, unicode)):

   if (new_cached_client_side_properties or
    self.__cached_user_agent is None or
    self.__cached_user_agent != user_agent_or_headers):

    self.__cached_user_agent = user_agent_or_headers
    self.__cached_headers = None
    self.__tree.put_properties(self.__cached_user_agent, self.__cached_headers,
     self.__cached_client_side_properties)
    self.__properties = self.__tree.properties

  # Headers
  else:

   if (user_agent_or_headers is not None and
    len(user_agent_or_headers) > 0 and
     (self.__cached_headers is None or
      self.__cached_headers != user_agent_or_headers)):

    self.__cached_user_agent = None
    self.__cached_headers = user_agent_or_headers
    self.__properties = self.__get_properties_from_headers(
     user_agent_or_headers,
     self.__cached_client_side_properties)

    # add language and locale properties
    language_header = "accept-language"
    if (self.__config.include_lang_props and
     language_header in self.__cached_headers):

     accept_language = self.__cached_headers[language_header]
     self.__add_language_properties(accept_language)

  if (self.__properties == {} and self.__config.return_none_when_no_properties):
   self.__properties = None

  elif (self.__properties is None and
   not self.__config.return_none_when_no_properties):
   self.__properties = {}

  return self.__properties

 # Private

 def __add_language_properties(self, accept_language):
  """
  Get the Accept-Language header and add language properties to the property
  list.
  @param accept_language: Accept-Language header.
  """

  if accept_language is None or accept_language.replace(' ', '') == '':
   return

  langs = accept_language.split(',')

  best = ''
  q_best = 0

  # go through the header parts
  for langs_i in langs:

   lang = langs_i.split(';')

   # get q
   q = 1

   if len(lang) > 1:
    s = lang[1].replace(' ', '')
    if s[0:2] == "q=":
     try:
      q = float(s[2:])
     except:
      q = 0
    else:
     continue # Invalid data

   # compare last best with current item, update if current item is better
   locale = lang[0].replace(' ', '') # lang or locale string
   length = len(locale)

   if (q > q_best or (q == q_best and length > 2 and length > len(best) and
   locale[0:2] == best[0:2])):
    best = locale
    q_best = q
    # if best item is found don't search more
    if length == 4 and q == 1:
     break

  # end for

  # set lang properties
  if best != "*":
   lang_locale = best.replace('_', '-').split('-')
   lang = lang_locale[0].lower()
   if len(lang_locale) == 2:
    locale = lang + '-' + lang_locale[1].upper()
   else:
    locale = None

   if lang != '':
    property_name_language = 'language'
    self.__tree.properties[property_name_language] = Property(lang, 's')
    if locale is not None and len(locale) == 5:
     property_name_language_locale = 'languageLocale'
     self.__tree.properties[property_name_language_locale] = Property(locale,
      's')

 def __get_property_as_byte(self, type_char):
  if type_char == 's':
   return DataType.STRING
  if type_char == 'b':
   return DataType.BOOLEAN
  if type_char == 'i':
   return DataType.INTEGER
  if type_char == 'd':
   return DataType.DOUBLE
  return DataType.UNKNOWN


 def __get_properties_from_headers(self, headers, client_side_properties):

  # make header keys lower-cased with no underlines
  self.__normalise_keys(headers)

  # get user-agent-header-name list from the tree object
  # collect the stock-ua headers if any exists
  stock_ua_headers = []
  tree_stock_ua_headers = self.__tree.stock_ua_headers

  for stock_ua_header in tree_stock_ua_headers:
   if stock_ua_header in headers:
    stock_ua_headers.append(headers[stock_ua_header])

  # get the user-agent header
  if "user-agent" in headers:
   ua = headers["user-agent"]
   stock_ua_headers.append(ua)
  else:
   ua = ''

  # ua is used for ua-props
  # stock_ua_headers is used for device detection, ua is added to the end of
  # this list
  self.__tree.put_properties(ua, stock_ua_headers, client_side_properties)

  return self.__tree.properties


 def __normalise_keys(self, headers):

  normalised_keys = {}
  original_keys = list(headers.keys())

  # Get normalised keys
  for key, value in headers.items():
   normalised_key = key.lower().replace('_','-').replace('http-','')
   normalised_keys[normalised_key] = value

  # Add normalised keys to headers
  for key, value in normalised_keys.items():
   headers[key] = value

  # Remove non-normalised headers if there are any
  for key in original_keys:
   if key not in normalised_keys:
    headers.pop(key)
