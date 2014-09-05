#   Version 4.0
import logging as logger
import splunk.clilib.cli_common as comm
from control_exceptions import *
import os, re, subprocess
import _internal

DB_MANIP   = os.path.join(comm.splunk_home, "bin", "dbmanipulator.py")

EXPORT_FILE    = "export.csv"
EXPORT_GZ_FILE = "export.csv.gz"

def getDef(args, fromCLI):
  """
  Show the default index.
  """
  paramsReq = ()
  paramsOpt = ()

  comm.validateArgs(paramsReq, paramsOpt, args)
  comm.requireSplunkdDown()

  #
  # No errors found, continue.
  #

  logger.info("Default index: ")
  os.system("python \"%s\" --showdefault" % DB_MANIP)


def setDef(args, fromCLI):
  """
  Set the new default index.
  """
  paramsReq = ("value",)
  paramsOpt = ()

  comm.validateArgs(paramsReq, paramsOpt, args)
  comm.requireSplunkdDown()

  #
  # No errors found, continue.
  #

  os.system("python \"%s\" --default \"%s\"" % (DB_MANIP, args["value"]))


def importAllFlatFiles(args, fromCLI):
  """
  Flat file import.  Run it before startup.
  """
  paramsReq = ()
  paramsOpt = ()
  comm.validateArgs(paramsReq, paramsOpt, args)
  comm.requireSplunkdDown()

  #
  # No errors found, continue.
  #

  paths = []
  # be sure to exclude tempPath lines.  on *nix, at least, /tmp can contain all sorts
  # of things that you don't have permission to read, so the search-for-*.gz step will
  # cause python exceptions all over the place.  brian says don't bother checking it.
  regex = re.compile("(?!tempPath.*=)[^=]*Path[^=]*= *(.*)")
  # should make comm.grep() do the right thing here. TODO
  # build "paths" here by taking the right side of all lines that have Path in them.
  for potentialPath in subprocess.Popen("btool indexes list --no-log",
    shell=True, stdout=subprocess.PIPE).stdout:
    result = regex.match(potentialPath)
    if None != result: # found a match.
      # add first [and only] match, replace $SPLUNK_DB in it while we're at it.
      paths.append(os.path.expandvars(result.groups()[0].strip()))

  for onePath in paths:
    import glob
    for bucket in glob.iglob(os.path.join(onePath, "db_*_*_*")):
      for export_file in (EXPORT_FILE, EXPORT_GZ_FILE):
        export_file = os.path.join(bucket, export_file)
        if os.path.isfile(export_file):
          do_import(bucket, export_file)
          break

def do_import(bucket, export_file):
  logger.info("importing %s" % bucket)
  if os.system("importtool \"%s\" \"%s\"" % (bucket, export_file)) == 0:
    os.remove(export_file)
  else:
    logger.error("error importing %s" % bucket)
