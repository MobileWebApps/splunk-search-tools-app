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

from mobi.mtld.da.device.post_walk_rules import PostWalkRules
from mobi.mtld.da.property import Property


class UaProps(PostWalkRules):
 """
 This class tries to extract properties from the User-Agent string itself. This
 is a completely separate step to the main JSON tree walk but uses the results
 of the tree walk to optimise the property extraction. The property extraction
 is done in two steps.

 Step 1: Try and identify the type of User-Agent and thus the set of property
 extraction rules to run. This is optimised by the properties from the tree
 walk.

 Step 2: Run the rules found in step 1 to try and extract the properties.
 """

 API_ID = 5

 # Constants to make keys more readable
 KEY_UA_RULES = 'uar'
 KEY_SKIP_IDS = 'sk'
 KEY_DEFAULT_REGEX_SET = 'd'
 KEY_RULE_GROUPS = 'rg'
 KEY_RULE_REGEX_ID = 'r'
 KEY_REGEXES = 'reg'
 KEY_REGEX_MATCH_POS = 'm'
 KEY_REFINE_REGEX_ID = 'f'
 KEY_SEARCH_REGEX_ID = 's'

 def __init__(self, tree_provider):
  super(UaProps, self).__init__(tree_provider, self.KEY_UA_RULES)
  # process the regexes - we need to override the default ones with any API
  # specific regexes
  self.__init_process_regexes()

 def put_properties(self, user_agent, props_to_vals, sought = None):
  # first check list of items that skip rules - these are typically non-mobile
  # boolean properties such as isBrowser, isBot etc

  if self.__skip_ua_rules(props_to_vals):
   return

  regexes = self.branch[self.KEY_REGEXES]

  # now find the rules to run on the UA. This is a two step process.
  # Step 1 identifies the UA type and finds as list of rules to run.
  # Step 2 uses the list of rules to find properties in a UA

  # STEP 1: try and find the rules to run on the UA
  rule_groups = self.branch[self.KEY_RULE_GROUPS]
  rules_to_run = self.__ua_property_rules(user_agent, props_to_vals,
   rule_groups, regexes)

  # STEP 2: try and extract properties using the rules
  if rules_to_run is not None:
   self.__extract_properties(rules_to_run, user_agent, regexes, sought)

 # Protected
 
 def _init_get_matcher_propery_ids(self, group, prop_ids):
  """
  Find all the properties that are used for matching.

  @param group: The rule group that can contain a property matcher
  @param prop_ids: The list of found property IDs
  """
  # the properties matcher may not exist....
  if group[self.KEY_PROPERTY_MATCHER]:
   for prop_id, prop_value in group[self.KEY_PROPERTY_MATCHER].items():
    if prop_id not in prop_ids:
     prop_ids.append(prop_id)

 def _init_rule_sets(self, group):
  """
  Prepare the rule set by extracting it from the current group and counting
  the items in the group. This is done to avoid counting the items on every
  request.

  @param group: The current parent group.
  """
  sets = group[self.KEY_RULE_SET]
  group[self.KEY_RULE_SET_COUNT] = len(sets)
  return sets

 # Private

 def __init_process_regexes(self):
  """
  Process the regexes by overriding any default ones with API specific regexes
  and then compile the list of regexes. This also changes the regex key from a
  string to an integer for easier retrieval later on.
  """
  # process regexes...
  # override default regexes if we have API specific ones to use
  all_reg = self.branch[self.KEY_REGEXES]
  default_reg = all_reg[self.KEY_DEFAULT_REGEX_SET]

  if self.API_ID in all_reg:
   # now loop over all api reg and replace the default regexes
   for key, reg_item in all_reg[self.API_ID].items():
    default_reg[key] = reg_item

  # no need to compile regexes

  # save some memory and remove the nodes we won't use by setting the main
  # regex node to be the new regex list
  self.branch[self.KEY_REGEXES] = default_reg

 def __extract_properties(self, rules_to_run, user_agent, regexes, sought):
  """
  This function loops over all the rules in rules_to_run and returns any
  properties that match. The properties returned can be typed or strings.

  @param rules_to_run: The rules to run against the User-Agent to find the
  properties.
  @param user_agent: The User-Agent to find properties for.
  @param regexes: The list of compiled regexes.
  @param sought: A set of properites to return values for.
  """

  # Loop over the rules array, each object in the array can contain 4 items:
  # propertyid, propertyvalue, regexid and regexmatch_position
  for rule_details in rules_to_run:

   ruleprop_id = rule_details[self.KEY_PROPERTY_MATCHER]

   # check if we are looking for a specific property, if so and the
   # current rule property id is not it then continue
   if (sought is not None) and (ruleprop_id not in sought):
    continue

   prop_name = self.tree_provider.property_name_by_id(ruleprop_id)

   # do we have a property we can set without running the regex rule?
   if self.KEY_PROPERTY_VALUE in rule_details:

    # we have an ID to the value...
    prop_val_id = rule_details[self.KEY_PROPERTY_VALUE]
    value = self.tree_provider.property_value_by_id(prop_val_id)

    self.tree_provider.properties[prop_name[1:]] = Property(value, prop_name[0])

   else:

    # otherwise apply the rule to extract the property from the UA
    regex_id = rule_details[self.KEY_RULE_REGEX_ID]
    patt = regexes[regex_id]

    matches = re.search(patt, user_agent)

    if matches is not None:
     match_pos = rule_details[self.KEY_REGEX_MATCH_POS]
     match_res = matches.group(match_pos)

     if match_res != "":

      value = match_res
      self.tree_provider.properties[prop_name[1:]] = Property(value,
       prop_name[0])

   # end else

  # end for

 # end method

 def __skip_ua_rules(self, id_properties):
  """
  Check list of items that skip rules - these are typically non-mobile boolean
  properties such as isBrowser, isBot, isCrawler, etc.

  @param id_properties: The results of the tree walk, map of property id to
  value id
  @return: TRUE if the UA rules are to be skipped, FALSE if they have to be run
  """
  skip_list = self.branch[self.KEY_SKIP_IDS]

  for prop_id in skip_list:

   str_prop_id = str(prop_id)

   if str_prop_id in id_properties:
    prop_val = self.tree_provider.property_value_by_id(id_properties[str_prop_id])
    if prop_val is not None and prop_val != 0: # 2nd condition is v. important
     return True
  return False

 def __ua_property_rules(self, user_agent, id_properties, rule_groups, regexes):
  """
  Try and find a set of property extraction rules to run on the User-Agent.
  This is done in two ways.

  The first way uses properties found from the tree walk to identify the
  User-Agent type. If there are still multiple UA types then refining regexes
  can be run.

  If the above approach fails to find a match then fall back to the second way
  which uses a more brute regex search approach.

  Once the UA type is known the correct set of property extraction rules can
  be returned.

  @param user_agent: The User-Agent to find properties for.
  @param id_properties: The results of the tree walk, map of property id to value id.
  @param rule_groups: All the rule groups that contain the matchers and the rules to
  run.
  @param regexes: The list of compiled regexes.
  @return: a map of rules to run against the User-Agent or None if no rules
  are found.
  """

  rules_to_run = []

  # Method one - use properties from tree walk to speed up rule search
  rules_to_run = self.__find_rules_by_properties(rule_groups, user_agent,
   id_properties, regexes)

  # No match found using the properties so now we loop over all rule groups
  # again and try to use a more brute force attempt to find the rules to run
  # on this user-agent.

  # continue to find extra rules even if we found rules from the property
  # matcher
  temp_rules = self.__find_rules_by_regex(rule_groups, user_agent, regexes)
  if temp_rules is not None and len(temp_rules) > 0:
   rules_to_run = rules_to_run + temp_rules # << Can be optimized

  return rules_to_run

 def __find_rules_by_properties(self, groups, user_agent, id_properties,
  regexes):
  """
  Try and find User-Agent type and thus the rules to run by using the
  properties returned from the tree walk. All the properties defined in the
  property matcher set must match. If a match is found then the rules can be
  returned.

  @param groups: The rule groups to loop over.
  @param user_agent: The User-Agent to find properties for.
  @param regexes: The list of compiled regexes.
  @return: a dict of rules to run against the User-Agent or None if no
  rules are found.
  """

  rules_to_run_a = []

  if groups is None or len(groups) == 0:
   return rules_to_run_a

  for group in groups:

   # check if we have the property match list
   if group is None or group[self.KEY_PROPERTY_MATCHER] is None:
    continue

   # try matching defined properties so we know what rules to run. If there
   # is a match then we can return the rules to run. In some cases we need to
   # refine the match found by running some refining regexes
   prop_match = self.__check_properties_match(group[self.KEY_PROPERTY_MATCHER],
    id_properties)

   if prop_match:
    rule_set = group[self.KEY_RULE_SET]
    rule_set_count = group[self.KEY_RULE_SET_COUNT]

    # in some cases we have multiple rule_sets to choose from, if more
    # than 1 we need to run some additional refining regex rules.

    if rule_set_count > 1:
     rules_to_run = self.__find_rules_to_run_by_regex(user_agent, rule_set,
      rule_set_count, regexes, self.KEY_REFINE_REGEX_ID)
    else:
     rules_set = rule_set[0] # 0th item... there should only be one...
     rules_to_run = rules_set[self.KEY_RULE_ARR]

    if len(rules_to_run) > 0:
     rules_to_run_a = rules_to_run_a + rules_to_run # << Can be optimized

  return rules_to_run_a

 def __check_properties_match(self, prop_list, props_to_values):
  """
  This functions checks all the properties in the property matcher branch of
  this rule group. This branch contains a list of properties and their values.
  All must match for this function to return true.

  In reality the properties and values are indexes to the main property and
  value arrays.

  @param prop_list: The list of properties to check for matches.
  @param props_to_values: Dict of property and value ids
  @return: TRUE if ALL properties match, false otherwise.
  """
  prop_match = False

  # loop over prop_list and try and match ALL properties
  for prop_id, expected_value_id in prop_list.items():

   # get the value found via the tree walk
   if prop_id in props_to_values:

    tree_value_id = props_to_values[prop_id]

    # we can speed things up a little by just comparing the IDs!
    if tree_value_id == expected_value_id:
     prop_match = True # no break here as we want to check all properties
    else:
     # there was code here to check actual values if the IDs did not match
     # but is was unnecessary. If the JSON generator is working correctly then
     # just the ID check is sufficient.
     return False

   else:
    return False

  return prop_match

 def __find_rules_by_regex(self, groups, user_agent, regexes):
  """
  Search for the rules to run by checking the User-Agent with a regex. If
  there is a match the rule list is returned.

  @param groups: The rule groups to loop over.
  @param user_agent: The User-Agent to find properties for.
  @param regexes: The list of compiled regexes.
  @return: a dict of rules to run against the User-Agent or nil if no rules
  are found.
  """
  rules_to_run = []

  if len(groups) > 0:

   i = 0
   n = len(groups)

   while i < n and len(rules_to_run) > 0:

    group = groups[i]
    rules_to_run = self.__find_rules_to_run_by_regex(
     user_agent,
     group[self.KEY_RULE_SET],
     group[self.KEY_RULE_SET_COUNT],
     regexes,
     self.KEY_SEARCH_REGEX_ID)

    i += 1

  return rules_to_run


 def __find_rules_to_run_by_regex(self, user_agent, rule_set, rule_set_count,
  regexes, type):
  """
  Loop over a set of refining rules to try and determine the User-Agent type
  and so find the rules to run on it.

  @param user_agent: The User-Agent to find properties for.
  @param rule_set: The rule_set that contains the search regex id, refine regex id
  and the magical rules_to_run.
  @param rule_set_count: The pre-counted items in rule_set.
  @param regexes: The list of compiled regexes.
  @param type: The type of rule to run either Refine or Search.
  @return: a dict of rules to run against the User-Agent or nil if no rules
  are found.
  """

  # we want these to run in the order they appear. For some reason the Json
  # class uses a Hash to represent an array of items so we have to loop
  # based on the index of the Hash

  for i in range(0, rule_set_count):

   set = rule_set[i]

   # get refine / search id to run
   if type in set:

    regex_id = set[type]

    # now look up the pattern...
    regex = regexes[regex_id]

    if re.search(regex, user_agent):
     return set[self.KEY_RULE_ARR] # now get the rules to run!

  return []
