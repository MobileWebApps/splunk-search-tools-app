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

class ClientPropsRuleSet(object):
 __user_agent = ''
 __rule_set = []

 def __init__(self, user_agent, rule_set):
  self.__user_agent = user_agent
  self.__rule_set = rule_set

 @property
 def user_agent(self):
  return self.__user_agent

 @property
 def rule_set(self):
  return self.__rule_set
