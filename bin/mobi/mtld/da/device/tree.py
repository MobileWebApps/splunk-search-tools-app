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

import re
try:
 import json as simplejson
except ImportError:
 import simplejson

from mobi.mtld.da.device.ua_props import UaProps
from mobi.mtld.da.device.client_props import ClientProps
from mobi.mtld.da.data_type import DataType
from mobi.mtld.da.property import Property
from mobi.mtld.da.properties import Properties
from mobi.mtld.da.exception.data_file_exception import DataFileException
from mobi.mtld.da.exception.client_properties_exception import ClientPropertiesException

class Tree(object):

 MIN_JSON_VERSION = 0.7

 # for MAP optimization, set to average number properties
 MAP_INITIAL_CAPACITY = 100

 # device-id property name
 KEY_DEVICE_ID = 'iid'

 # tree key - {DATA-META-DATA}
 KEY_META = '$'

 # tree key - tree structure version
 KEY_META_VERSION = 'Ver'

 # tree key - tree revision
 KEY_META_REVISION = 'Rev'

 # tree key - tree create time-stamp
 KEY_META_TIMESTAMP = 'Utc'

 # tree key - property names [property-name,]
 KEY_PROPERTY_NAMES = 'p'

 # tree key - property values [property-value,]
 KEY_VALUES = 'v'

 # tree key - list of regexes [regex(String),]
 KEY_REGEX = 'r'

 # tree key - list of compiled regexes, the regexes are compiled and put inside
 # [regex(Pattern),]
 KEY_COMPILED_REGEX = 'creg'

 # tree key - user-agent header names
 # {"h":{"sl":["x-device-user-agent","x-original-user-agent"]}}
 KEY_HEADERS = 'h'

 # tree key - stock user-agent header names
 # {"h":{"sl":["x-device-user-agent","x-original-user-agent"]}}
 KEY_UA_STOCK_HEADERS = 'sl'

 # tree key - tree main branch
 KEY_MAIN = 't'

 # tree key - property data
 KEY_DATA = 'd'

 # tree key - has children
 KEY_CHILDREN = 'c'

 # tree key - masked properties
 KEY_MASKED = 'm'

 properties = None
 tree = None
 data_revision = None

 # A list of http-headers which may contain the original user-agent.
 # if the tree does not contain KEY_UA_STOCK_HEADERS then this list will be
 # used
 stock_ua_headers = []

 __config = None
 __ua_props = None
 __client_props = None
 __device_id_prop_name_id = None


 def __init__(self, json, config):
  """
  Load the JSON tree into a dict.
  """
  self.__config = config

  self.tree = simplejson.loads(json)

  if self.tree == {}:
   raise DataFileException('Unable to load JSON data')

  if self.KEY_META not in self.tree:
   raise DataFileException('Bad data loaded into the tree')

  if (float(self.tree[self.KEY_META][self.KEY_META_VERSION]) <
  self.MIN_JSON_VERSION):
   raise DataFileException('DeviceAtlas JSON file must be version 0.7 or ' +
   'later. Please download a more recent version')

  # Prepare the user-agent rules branch before we start recognition.
  # To maintain backwards compatibility - only do this if we have the ua rules
  # branch
  if UaProps.KEY_UA_RULES in self.tree and self.__config.include_ua_props:
   self.__ua_props = UaProps(self) # stick in the tree so we can use it later
   # remove the UAR branch to save some memory
  elif UaProps.KEY_UA_RULES in self.tree:
   del self.tree[UaProps.KEY_UA_RULES]

  # Prepare client side properties.
  if ClientProps.KEY_CP_RULES in self.tree:
   self.__client_props = ClientProps(self)

  # cache values from the tree which are used by the API
  property_ids = self.tree[self.KEY_PROPERTY_NAMES]

  i = 0
  for property_id in property_ids:
   if self.KEY_DEVICE_ID == property_id:
    self.__device_id_prop_name_id = str(i)
    break
   i += 1

  # set ua headers
  self.stock_ua_headers = [
   "x-device-user-agent",
   "x-original-user-agent",
   "x-operamini-phone-ua",
   "x-skyfire-phone",
   "x-bolt-phone-ua",
   "device-stock-ua",
   "x-ucbrowser-ua",
   "x-ucbrowser-device-ua",
   "x-ucbrowser-device",
   "x-puffin-ua"
  ]

  # update stock user-agent headers from tree
  if self.KEY_HEADERS in self.tree and self.tree[self.KEY_HEADERS] is not None:
   ua_stock_headers = self.tree[self.KEY_HEADERS][self.KEY_UA_STOCK_HEADERS]
   if ua_stock_headers is not None:
    self.stock_ua_headers = ua_stock_headers

  # set data revision
  self.data_revision = self.tree[self.KEY_META][self.KEY_META_REVISION]

 def property_names(self):
  """
  Get the list of all available property names from the tree (not contains
  client side props)
  """
  return self.tree[self.KEY_PROPERTY_NAMES]

 def data_version(self):
  """
  Get data file version.
  """
  return self.tree[self.KEY_META][self.KEY_META_VERSION]

 def data_creation_timestamp(self):
  """
  Get data file creation timestamp.
  """
  return self.tree[self.KEY_META][self.KEY_META_TIMESTAMP]

 def put_properties(self, user_agent, stock_user_agents,
  client_side_properties = None):
  """
  Get properties from tree walk/ua/client-side and put them in the
  tree.properties

  @param user_agent: user-agent string (from the original User-Agent header) to be
  used for detecting ua-props
  @param stock_user_agents: list of candidate user-agent strings to be used for
  tree walk
  @param client_side_properties: optional client side properties
  """

  self.properties = Properties()

  self.put_tree_walk_properties(user_agent, stock_user_agents)

  if client_side_properties is not None and client_side_properties != "":
   if self.__client_props is None:
    # stop if the JSON file does not contain the required CPR section
    raise ClientPropertiesException('JSON data does not support client ' +
    'properties.')
   self.__client_props.put_properties(client_side_properties)

 def put_tree_walk_properties(self, user_agent, stock_user_agents = None):
  """
  Get properties from tree walk/ua and put them in the tree.properties

  if stock_user_agents is not None:
   - iterate over stock_user_agents
     for each item: tree-walk and stop iteration if result has deviceId
   - use userAgent for detecting the ua-props

  if stock_user_agents is None:
   - use userAgent for tree walk
   - use userAgent for detecting the ua-props

  @param user_agent: user-agent string (from the original User-Agent header)
  @param stock_user_agents: list of candidate user-agent strings to be used for
  tree walk
  """

  include_ua_props = self.__config.include_ua_props

  # props_to_vals = {property-id-from-tree-p: value-id-from-tree-v,}
  props_to_vals = {}
  regexes = self.tree[self.KEY_REGEX][str(UaProps.API_ID)]
  tree_main = self.tree[self.KEY_MAIN]
  matched = ""

  # Remove spaces and backslashes
  user_agent = user_agent.strip().replace("\/", "/")

  if stock_user_agents is None:

   self.__seek_properties(tree_main, user_agent, props_to_vals, matched,
    regexes)

  else:

   for stock_user_agent in stock_user_agents:
    stock_user_agent = stock_user_agent.replace("\/", "/")
    self.__seek_properties(tree_main, stock_user_agent, props_to_vals, matched,
    regexes)
    if self.__device_id_prop_name_id in props_to_vals:
     break

  # put the detected properties which are as
  # {property-id-from-tree-p: value-id-from-tree-v,}
  # into the (Properties) properties object
  for property_id, value_id in props_to_vals.items():
   name = self.property_name_by_id(int(property_id))
   self.properties[name[1:]] = Property(self.property_value_by_id(value_id),
    name[0])

  # matched and un-matched
  if self.__config.include_match_info:
   # add in matched and unmatched UA parts
   self.properties['_matched'] = Property(matched, DataType.STRING)
   self.properties['_unmatched'] = Property(user_agent[len(matched):],
    DataType.STRING)

  # get ua-props from the original user-agent header
  if include_ua_props and self.__ua_props is not None:
   self.__ua_props.put_properties(user_agent, props_to_vals)


 def property_name_by_id(self, property_id):
  return self.tree[self.KEY_PROPERTY_NAMES][property_id]

 def property_value_by_id(self, value_id):
  return self.tree[self.KEY_VALUES][value_id]

 # Private

 def __seek_properties(self, node, string, props_to_vals, matched, regex_rules,
  sought = None):

  if self.KEY_DATA in node and node[self.KEY_DATA] is not None:
   data = node[self.KEY_DATA]
   if sought is None:
    for key, value in data.items():
     props_to_vals[key] = value

   else:
    for name_id in sought:
     value_id = data[name_id]
     if value_id is not None:
      props_to_vals[name_id] = value_id
      if self.KEY_MASKED not in node or name_id not in node[self.KEY_MASKED]:
       del sought[name_id]
       if sought is None or len(sought) == 0:
        return

  if self.KEY_CHILDREN in node:
   if self.KEY_REGEX in node:
    to_run = node[self.KEY_REGEX]
    max_regex_rules = len(regex_rules)
    for to_run_j in to_run:
     if to_run_j < max_regex_rules:
      patt = regex_rules[to_run_j]
      string = re.sub(patt, '', string)
   # recursively walk the tree
   if string is not None:
    length = len(string) + 1
    children = node[self.KEY_CHILDREN]
    for k in range(0, length):
     seek = string[0:k]
     if seek in children:
      matched += seek
      return self.__seek_properties(children[seek], string[k:], props_to_vals,
       matched, regex_rules, sought)
