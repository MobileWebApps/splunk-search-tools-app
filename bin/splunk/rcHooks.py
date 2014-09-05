
"""File containing generic functions which as as pre/post hooks for the cli."""

import os
import logging as logger

import splunk.rest as rest
import splunk.util as util
from splunk.rest.format import nodeToPrimitive, AtomEntry, AtomFeed
from splunk.clilib.control_exceptions import ArgError

thresholdMap = {
  "num-events"  : "number of events",
  "num-sources" : "number of sources",
  "num-hosts"   : "number of hosts",
  "always"      : "always"
}

relationMap = {
  "greater-than"  : "greater than",
  "less-than"     : "less than",
  "equal-to"      : "equal to",
  "rises-by"      : "rises by",
  "drops-by"      : "drops by"
}


def map_args_cli_2_eai(argsmap, eaiArgsList, argList):
   """Map the cli argument names to the appropriate eai argument names.

   Args:
      argsmap: map containing the map of cli arg name <=> eai arg names
      eaiArgsList: the destination dict that will contain keys which are the eai arg names
      argList: the sourse dict that will contain keys which are the cli arg names

   Returns:
      the eaiArgsList which acts as the GET/POST parms of the EAI request
   """
   for k in argList:
      try:
         eaiArgsList[argsmap[k]] = argList[k]
      except:
         eaiArgsList[k] = argList[k]

   return eaiArgsList

def make_path_absolute(cmd, obj, eaiArgsList):
   """Ensures the contents of eaiArgsList['name'] is absolute."""
   logger.debug('In function make_path_absolute, eaiArgsList: %s' % str(eaiArgsList))
   if obj in ['tail', 'monitor']:
       key = 'source'
   else:
       key = 'name'
   try:
      if not os.path.isabs(eaiArgsList[key]):
         eaiArgsList[key] = os.path.abspath(eaiArgsList[key])
   except:
      pass

def conv_to_list(cmd, obj, eaiArgsList):
   """Converts a value in the dict to a list."""
   if '%s:%s' % (cmd,obj) == 'set:default-index':
      if eaiArgsList.has_key('value'):
         eaiArgsList['value'] = eaiArgsList['value'].split(',')

# ----------------------------
def _parseThreshold(thresh):
  """ 
  Figure out threshold in the format "num-events:rises-by:5".
  """
  try:
    threshType, threshRel, threshVal = thresh.split(':', 2)
  except ValueError:
    raise ArgError, "The argument to 'threshold' must be in the form <threshold type>:<threshold relation>:<threshold value>."
  if not threshType.lower() in thresholdMap.keys():
    raise ArgError, "Invalid threshold type '%s' specified for 'threshold'.  Valid types are: %s." % (threshType, str.join(", ", thresholdMap.keys()))
  if not threshRel.lower() in relationMap.keys():
    raise ArgError, "Invalid threshold relation '%s' specified for 'threshold'.  Valid relations are: %s." % (threshRel, str.join(", ", relationMap.keys()))
  if not threshVal.isdigit():
    raise ArgError, "Invalid threshold value '%s' specified for 'threshold'.  Threshold value must be a number." % threshVal

  return thresholdMap[threshType.lower()], relationMap[threshRel.lower()], threshVal


def parse_saved_search(cmd, obj, eaiArgsList):
   """Funky saved-search argument parsing."""
   action = []

   #alert
   if eaiArgsList.has_key('alert') and util.normalizeBoolean(eaiArgsList['alert']):
      eaiArgsList['is_scheduled'] = '1'
      eaiArgsList.pop('alert')
   else:
      eaiArgsList['is_scheduled'] = '0'

   #threshold
   if eaiArgsList.has_key('threshold'):

      alert_type, alert_comparator, alert_threshold = _parseThreshold(eaiArgsList['threshold'])

      eaiArgsList['alert_type'] = alert_type
      eaiArgsList['alert_comparator'] = alert_comparator
      eaiArgsList['alert_threshold'] = alert_threshold
      eaiArgsList.pop('threshold')

   #email
   if eaiArgsList.has_key('email'):
      eaiArgsList['action.email.to'] = eaiArgsList['email']
      eaiArgsList.pop('email')
      action.append('emai')

   #attach
   if eaiArgsList.has_key('attach'):
      eaiArgsList['action.email.sendresults'] = '1'
      eaiArgsList.pop('attach')

   #script
   if eaiArgsList.has_key('script'):
      eaiArgsList['action.script.filename'] = eaiArgsList['script']
      eaiArgsList.pop('script')
      action.append('script')

   #summary_index
   if eaiArgsList.has_key('summary_index'):
      eaiArgsList['action.summary_index._name'] = eaiArgsList['summary_index']
      eaiArgsList.pop('summary_index')
      action.append('summary_index')

   #action
   eaiArgsList['actions'] = ','.join(action)

   #start_time
   if eaiArgsList.has_key('start_time'):
      eaiArgsList['dispatch.earliest_time'] = eaiArgsList['start_time']
      eaiArgsList.pop('start_time')

   #end_time
   if eaiArgsList.has_key('end_time'):
      eaiArgsList['dispatch.latest_time'] = eaiArgsList['end_time']
      eaiArgsList.pop('end_time')

   #ttl
   if not eaiArgsList.has_key('dispatch.ttl'):
      if eaiArgsList.has_key('ttl'):
         eaiArgsList['dispatch.ttl'] = eaiArgsList['ttl']
         eaiArgsList.pop('ttl')

   #fields
   if eaiArgsList.has_key('fields'):
      items = eaiArgsList['fields'].split(';')
      for ele in items:
         if len(ele.split(':')) != 2:
            raise ArgError, "Each argument to 'fields' must be in 'key:value' format"
         k,v = ele.split(':')
         eaiArgsList['%s.%s' % ('action.summary_index',k)] = v
      eaiArgsList.pop('fields')

def get_index_app(servResp, argList):
   """"""
   atom = rest.format.parseFeedDocument(servResp)

   for entry in atom:
      d = nodeToPrimitive(entry.rawcontents)
      if entry.title == argList['name']:
         return d['eai:acl']['app']

 
