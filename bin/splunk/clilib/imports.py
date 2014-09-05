#   Version 4.0
import logging as logger
import splunk.clilib.cli_common as comm
import os, shutil, sys
import xml.dom.minidom
import control_exceptions as ce
import bundle_paths

# TODO: should the server be up, down, or either for these operations?

def imUserSplunk(args, fromCLI):
  """
  Import users and splunks.
  """
  paramsReq = ("dir",)
  paramsOpt = ()

  comm.validateArgs(paramsReq, paramsOpt, args)

  bakDir = os.path.normpath(args["dir"])

  #
  # No errors found, continue.
  #

  logger.info("Restoring user data from dir: %s." % bakDir)

  PASS_NAME     = "passwd"
  PASS_FILE_BAK = os.path.join(bakDir, PASS_NAME)
  PASS_FILE     = os.path.join(comm.splunk_home, "etc", PASS_NAME)

  filename, oldFilePath, newFilePath = (PASS_NAME, PASS_FILE_BAK, PASS_FILE)
  if os.path.exists(oldFilePath):
    shutil.copy(oldFilePath, newFilePath)
  else:
    if filename in (PASS_NAME,):
      logger.info("No '%s' file found in supplied backup dir '%s'. Did you supply an incorrect directory?" % (filename, bakDir))

  try:
    importer = bundle_paths.BundlesImporter()
    site = bundle_paths.BundlesImportExportSite(bakDir)
    importer.do_import(site)
  except bundle_paths.BundleException, e:
    raise ce.FilePath, ("Unable to import: %s.  Aborting restore." % e)
