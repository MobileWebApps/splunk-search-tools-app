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

from mobi.mtld.da.device.client_props_rule_set import ClientPropsRuleSet
from mobi.mtld.da.device.post_walk_rules import PostWalkRules
from mobi.mtld.da.property import Property
from mobi.mtld.da.exception.client_properties_exception import ClientPropertiesException

class ClientProps(PostWalkRules):

 # Constants to make keys more readable
 KEY_CP_RULES = 'cpr'
 KEY_USER_AGENT = 'ua'

 def __init__(self, tree):
  super(ClientProps, self).__init__(tree, self.KEY_CP_RULES)

 def put_properties(self, client_side_properties):
  """
  Put Client Side properties into the property set.

  The first character of the property name is the type of the value.

  @param client_side_properties: Cookie content with the following format:
   bjs.webGl:1|sdeviceAspectRatio:16/10|iusableDisplayHeight:1050
  """

  # "merge with detected properties" and "get" the props from the client side
  # cookie
  client_side_properties = self.parse_client_side_properties(
  client_side_properties)

  # use the merged properties to look up additional rules

  # STEP 1: try and find the rules to run on the UA
  rule_groups = self.branch[self.KEY_RULE_GROUPS]
  rules_to_run = self.__rules_to_run(rule_groups)

  # STEP 2: do second tree walk if necessary and replace/create any new
  # values based on the rules
  if rules_to_run is None:
   return

  user_agent = rules_to_run.user_agent

  if user_agent is not None:

   # use the UA for a second tree walk - note the last param is
   # false as we know the UA won't have any dynamic properties
   # also sought = nil
   self.tree_provider.put_tree_walk_properties(user_agent)

   # merge origProperties in to get any parent properties such as the dynamic
   # properties 2nd tree walk > first tree walk

   # the client properties still take priority so merge them in again
   # client props > tree walks
   for name, value in client_side_properties.items():
    self.tree_provider.properties[name[1:]] = Property(value, name[0])

   # overlay the new properties
   rule_set = rules_to_run.rule_set
   for prop_id_val_id in rule_set:
    name = self.tree_provider.property_name_by_id(
     prop_id_val_id[self.KEY_PROPERTY_MATCHER])
    value = self.tree_provider.property_value_by_id(
     prop_id_val_id[self.KEY_PROPERTY_VALUE])
    self.tree_provider.properties[name[1:]] = Property(value, name[0])


 def parse_client_side_properties(self, client_side_properties):
  """
  Parse the client side properties and if typed values is set convert the
  values to the appropriate type.

  The first character of the property name is the type of the value.

  @param client_side_properties: Cookie content with the form:
   bjs.webGl:1|sdeviceAspectRatio:16/10|iusableDisplayHeight:1050  
  """

  # Table to replace HTML escape characters from property values in the cookie
  # content.
  html_escape_characters = {'&': '&amp;', '"': '&quot;', '<': '&lt;',
  '>': '&gt;'}

  props = {}
  client_side_properties = client_side_properties.strip()

  try:

   name = ''
   value = ''
   is_key = True
   is_type = True
   key_ok = True
   type = 0

   num_chars = len(client_side_properties) - 1

   # iterate over the property string looking for properties and values
   max_i = num_chars + 1
   for i in range(0,max_i): # Loop from 0 to num_chars-1

    c = client_side_properties[i]

    if c == '|':

     # if key is valid add property
     if key_ok:
      type = name[0]
      props[name] = value # No need of typifying it
      self.tree_provider.properties[name[1:]] = Property(value, type)

     # reset for next key/value
     name = ''
     value = ''
     is_key = True
     key_ok = True
     is_type = True

     continue # skip to the next character

    elif c == ':':

     is_key = False
     continue # skip to the next character

    elif c == '"':

     if i < num_chars:
      next_c = client_side_properties[i+1]
     else:
      next_c = 0

     if (i == 0 or i == num_chars or is_key or len(value) == 0 or
      next_c == '|' or next_c == '"'):
      continue # skip any wrapping quotes

    # end if c == '|'

    if is_key:
     # check if property type and name are correct
     if is_type:
      if c != 'b' and c != 'i' and c != 's' and c != 'd':
       key_ok = False
      is_type = False
     else:
      c_ord = ord(c)
      if ((c_ord < 48 and c_ord != 46) or c_ord > 122 or
       (c_ord > 57 and c_ord < 65) or (c_ord > 90 and c_ord < 97)):
       key_ok = False
     name += c
    else:
     if c in html_escape_characters:
      value += html_escape_characters[c]
     else:
      value += c
   # end of for

   # add the last prop value
   if key_ok:
    type = name[0]
    props[name] = value # No need of typifying it
    self.tree_provider.properties[name[1:]] = Property(value, type)

  except Exception as e:
   raise ClientPropertiesException(
    "Could not decode client properties: %s" % e.message)

  return props

 # Protected

 def _init_get_matcher_propery_ids(self, group, prop_ids):
  """
  Find all the properties that are used for matching.

  @param group: The rule group that can contain a property matcher.
  @param prop_ids: The set of found property IDs.
  It returns an updated set of property IDs.
  """
  if group[self.KEY_PROPERTY_MATCHER]:
   property_matchers = group[self.KEY_PROPERTY_MATCHER]
   for property_matcher in property_matchers:
    prop_id = property_matcher[self.KEY_PROPERTY_MATCHER]
    if prop_id not in prop_ids:
     prop_ids.append(prop_id)
  return prop_ids

 def _init_rule_sets(self, group):
  """
  Prepare the rule set by extracting it from the current group and wrapping
  it in a list.

  @param group: The current parent group.
  It returns a list of all rule sets.
  """
  # wrap the single rule set in an array list.
  return [{ self.KEY_RULE_ARR: group[self.KEY_RULE_ARR] }]

 # Private

 def __rules_to_run(self, groups):

  for group in groups:

   property_matchers = group[self.KEY_PROPERTY_MATCHER]

   # try matching defined properties so we know what rules to run. If there
   # is a match then we can return the rules to run.
   prop_match = self.__check_properties_match(property_matchers)

   if prop_match:
    if self.KEY_USER_AGENT in group:
     user_agent = group[self.KEY_USER_AGENT]
    else:
     user_agent = ''
    rule_set = group[self.KEY_RULE_ARR]
    return ClientPropsRuleSet(user_agent, rule_set)

  return None

 def __check_properties_match(self, property_matchers):

  # loop over property_matchers and try and match ALL properties
  for matcher_details in property_matchers:

   prop_id = matcher_details[self.KEY_PROPERTY_MATCHER]
   prop_name_type = self.tree_provider.property_name_by_id(prop_id)
   prop_name = prop_name_type[1:]

   # compare the detected value to the expected value
   if prop_name in self.tree_provider.properties:

    detected_property = self.tree_provider.properties.get(prop_name)

    # get the expected value
    prop_val_id = matcher_details[self.KEY_PROPERTY_VALUE]
    expected_value = self.tree_provider.property_value_by_id(prop_val_id)
    operator = matcher_details[self.KEY_OPERATOR]

    # It is important to compare the property values with the same type
    if not self.__compare_values(
     str(detected_property.value),
     str(expected_value),
     operator,
     prop_name_type[0]):
     return False

   else:
    return False

  return True

 def __compare_values(self, detected_value, expected_value, operator,
 type_prop_name):
  result = False
  operator_equals = '='
  operator_not_equals = '!='
  operator_less_than = '<'
  operator_less_than_equals = '<='
  operator_greater_than = '>'
  operator_greater_than_equals = '>='

  t = type_prop_name[0]

  if t in ('s', 'b'):
   if operator == operator_equals:
    result = (detected_value == expected_value)
   elif operator == operator_not_equals:
    result = (not detected_value == expected_value)
   elif t == 'i':
    d_val = int(detectedValue)
    e_val = int(expectedValue)

    if d_val == e_val and (operator in(operator_equals,
     operator_less_than_equals, operator_greater_than_equals)):
     result = True
    elif d_val > e_val and (operator in(operator_greater_than,
     operator_greater_than_equals)):
     result = True
    elif d_val < e_val and (operator in(operator_less_than,
     operator_less_than_equals)):
     result = True
    elif d_val != e_val and operator == operator_not_equals:
     result = True

  return result
