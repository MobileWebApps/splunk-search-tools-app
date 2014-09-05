import logging as logger
import os, shutil
import cli_common as comm
import control_exceptions as cex
import bundle_paths

ARG_APPNAME = "name"

FILE_INSTALL   = "setup.py"
FILE_UNINSTALL = "setup.py"

def getAppPaths(name):
  disabledApp = os.path.join(comm.splunk_home, "etc", "disabled-apps", name)
  enabledApp  = os.path.join(comm.splunk_home, "etc", "apps",          name)
  return (disabledApp, enabledApp)

def localIsAppEnabled(appName):
  app = bundle_paths.get_bundle(appName)
  if None == app:
    raise cex.FilePath, "Application '%s' not found." % appName

  return app.is_enabled()

def localAppDisable(args, fromCLI):
  """
  Works only on the local filesystem.
  Disables app of given name.
  """
  paramsReq = (ARG_APPNAME,)
  paramsOpt = ()
  comm.validateArgs(paramsReq, paramsOpt, args)

  returnDict = {}
  appName = args[ARG_APPNAME]

  return disableApp(appName, fromCLI)

def disableApp(appName, fromCLI):
  app = bundle_paths.get_bundle(appName)
  if None == app:
    raise cex.FilePath, "Application '%s' not found." % appName

  currEnabled = app.is_enabled()

  returnDict = {}
  if currEnabled: # then disable it
    returnDict["restartRequired"] = True
    app.disable()

  if fromCLI:
    if not currEnabled:
      logger.info("%s is already disabled." % appName)
    else:
      logger.info("%s disabled." % appName)
  return returnDict


def localAppEnable(args, fromCLI):
  """
  Works only on the local filesystem.
  Enables app of given name.
  """
  paramsReq = (ARG_APPNAME,)
  paramsOpt = ()
  comm.validateArgs(paramsReq, paramsOpt, args)
  appName = args[ARG_APPNAME]

  returnDict = {}
  return enableApp(appName, fromCLI)


def enableApp(appName, fromCLI):  
  app = bundle_paths.get_bundle(appName)
  if None == app:
    raise cex.FilePath, "Application '%s' not found." % appName

  currEnabled = app.is_enabled()

  returnDict = {}
  if not currEnabled: # then enable it
    returnDict["restartRequired"] = True
    app.enable()

  if fromCLI:
    if currEnabled:
      logger.info("%s is already enabled." % appName)
    else:
      logger.info("%s enabled." % appName)
  return returnDict


def localAppStatus(args, fromCLI):
  """
  Works only on the local filesystem.
  Shows whether app of given name is enabled
  """
  paramsReq = (ARG_APPNAME,)
  paramsOpt = ()
  comm.validateArgs(paramsReq, paramsOpt, args)

  returnDict = {}
  app = bundle_paths.get_bundle(args[ARG_APPNAME])
  if None == app:
    raise cex.FilePath, "Application '%s' not found." % args[ARG_APPNAME]
  currEnabled = app.is_enabled()

  if fromCLI:
    if currEnabled:
      logger.info("%s is enabled." % args[ARG_APPNAME])
    else:
      logger.info("%s is disabled." % args[ARG_APPNAME])
  return returnDict
