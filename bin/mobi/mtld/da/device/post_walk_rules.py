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

class PostWalkRules(object): 

 class PostWalkRulesException(DeviceAtlasException):
  """
  The PostWalkRulesException exception is raised by this class when the
  init_get_matcher_propery_ids() or init_rule_sets() are called before they
  have been replaced by any new implementation from a child class.
  This helps us to simulate abstract methods, which does not exist in Ruby.
  """
  pass

 # Constants to make keys more readable
 KEY_PROPERTY_MATCHER = 'p'
 KEY_PROPERTY_VALUE = 'v'
 KEY_OPERATOR = 'o'
 KEY_MATCHER_PROP_IDS_IN_USE = 'mpids'
 KEY_RULE_ARR = 'r'
 KEY_RULE_PROP_IDS_IN_USE = 'rpids'
 KEY_RULE_GROUPS = 'rg'
 KEY_RULE_SET = 't'
 KEY_RULE_SET_COUNT = 'tc'

 tree_provider = None
 branch = {}
 __prop_matcher_ids_in_use = []
 __rule_prop_ids_in_use = []


 def __init__(self, tree_provider, type):
  self.tree_provider = tree_provider

  self.branch = tree_provider.tree[type] # main branch

  rg = self.branch[self.KEY_RULE_GROUPS]

  for group in rg:
   # We want to keep a list of all the properties that are used because when
   # a user calls DeviceApi.properties we need to fetch additional properties
   # other than the property they want to optimize the User-Agent string
   # rules.
   self._init_get_matcher_propery_ids(group, self.__prop_matcher_ids_in_use)

   sets = self._init_rule_sets(group)

   # Also keep a list of all the property IDs that can be output
   self.__rule_prop_ids_in_use = self.__init_get_rule_property_ids(sets,
    self.__rule_prop_ids_in_use)

 # Protected

 def _init_get_matcher_propery_ids(self, group, prop_ids):
  """
  Find all the properties that are used for matching. This is needed in case
  the DeviceApi.properties function is called as we need these properties
  for the rules to work correctly.

  @param group: The rule group that can contain a property matcher.
  @param prop_ids: The list of found property IDs.
  @return: an updated set of property IDs.
  """
  raise PostWalkRulesException('This is an abstract method that has not been ' +
   'implemented.')

 def _init_rule_sets(self, group):
  """
  Prepare the rule set
  @param group: The current parent group.
  @return: a list of all rule sets.
  """
  raise PostWalkRulesException('This is an abstract method that has not been ' +
   'implemented.')

 # Private

 def __init_get_rule_property_ids(self, sets, rule_prop_ids):
  """
  Find all the properties that are used in the final rules. This is needed to
  optimize the Api.getProperty() function.

  @param sets: The rule set from the main rule group.
  @param rule_prop_ids: The list of found property IDs.
  @return: an updated set of property IDs.
  """

  # loop over all items in the rule set and find all the property ids
  # used in the rules

  for items in sets:
   rules = items[self.KEY_RULE_ARR]

   if rules is None:
    return rule_prop_ids

   # now loop over the actual rule array
   for rule_details in rules:

    prop_id = rule_details[self.KEY_PROPERTY_MATCHER]

    if prop_id not in rule_prop_ids:

     rule_prop_ids.append(prop_id)

  return rule_prop_ids
