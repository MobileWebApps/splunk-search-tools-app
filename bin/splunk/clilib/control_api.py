#   Version 4.0
import logging as logger
import copy

import splunk.clilib.cli_common as comm
from control_exceptions import *
from literals import *

import _internal
import info_gather

import apps
import bundle
import bundle_paths
import deploy
import exports
import index
import migration
import module
import manage_search as ms
import test
import train
import i18n

def newFunc(func):
  def wrapperFunc(args, fromCLI = False):
    if not isinstance(args, dict):
      raise ArgError, "Parameter 'args' should be a dict (was %s)." % type(args)
    dictCopy = copy.deepcopy(args)
    return func(dictCopy, fromCLI)
  return wrapperFunc


#### ----- MANAGE_SEARCH -----
getUIVersion = newFunc(ms.getUIVersion)
setUIVersion = newFunc(ms.setUIVersion)
get_servername = newFunc(ms.getInstanceName)
setServerName = newFunc(ms.setInstanceName)

### ----- TEST -----

testDates  = newFunc(test.testDates)
testFields = newFunc(test.testFields)
testStypes = newFunc(test.testSourcetypes)

### ----- TRAIN -----

trainDates  = newFunc(train.trainDates)
trainFields = newFunc(train.trainFields)


### ----- INDEXES -----

get_defIndex = newFunc(index.getDef)
set_defIndex = newFunc(index.setDef)

### ----- DEPLOYMENT CLIENT SETTINGS -----

deplClient_disable = newFunc(module.deplClientDisable)
deplClient_enable = newFunc(module.deplClientEnable)
deplClient_status = newFunc(module.deplClientStatus)
deplClient_edit = newFunc(deploy.editClient)
get_depPoll = newFunc(deploy.getPoll)
set_depPoll = newFunc(deploy.setPoll)

### ----- BUNDLE MANAGEMENT -----

bundle_migrate = newFunc(bundle_paths.migrate_bundles)

### ----- DIRECT CONFIG INTERACTION -----

showConfig = newFunc(bundle.showConfig)

### ----- EXPORTING DATA ----- # the rest of export & import should be here too.. TODO

export_eventdata = newFunc(exports.exEvents)

### ----- INTERNAL SETTINGS -----

def set_uri(uri, fromCLI = False):
  comm.setURI(uri)


### ----- MIGRATION -----
mig_winSavedSearch = newFunc(migration.migWinSavedSearches)


### ----- SOME LOCAL FILESYSTEM FUNCTIONS -----
local_moduleStatus  = newFunc(module.localModuleStatus)
local_moduleEnable  = newFunc(module.localModuleEnable)
local_moduleDisable = newFunc(module.localModuleDisable)
local_appStatus     = newFunc(apps.localAppStatus)
local_appEnable     = newFunc(apps.localAppEnable)
local_appDisable    = newFunc(apps.localAppDisable)


### ----- I18N -----
i18n_extract = newFunc(i18n.i18n_extract)

### ----- OTHER INTERNALISH STUFF -----

checkXmlFiles   = newFunc(_internal.checkXmlFiles)
firstTimeRun    = newFunc(_internal.firstTimeRun)
preFlightChecks = newFunc(_internal.preFlightChecks)
diagnose        = newFunc(info_gather.pclMain)
