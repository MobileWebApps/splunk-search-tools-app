#   Version 4.0
import logging as logger
import os, manage_search, shutil, socket, subprocess, sys, xml.dom.minidom
import build_info, index, migration
import splunk.clilib.cli_common as comm
import control_exceptions as cex
import bundle_paths

ARG_DRYRUN    = "dry-run"
ARG_FRESHINST = "is-fresh-install"
ARG_LOGFILE   = "log-file"

PARM_TRUE     = "true"

DEFAULT_SERVER_NAME  = "server_name_in_splunkd.xml"

# TODO move this to common
PATH_DB_MANIPULATOR  = os.path.join(comm.splunk_home, "bin", "dbmanipulator.py")
PATH_FTR_FILE        = os.path.join(comm.splunk_home, "ftr")
PATH_LICENSE_FILE    = os.path.join(comm.splunk_home, "license-eula.txt")
PATH_SELINUX_CONFIG  = os.path.join(os.path.sep, "etc", "selinux", "config")
PATH_AUDIT_KEY_DIR   = os.path.join(comm.splunk_home, "etc", "auth", "audit")
PATH_AUDIT_PRIV_KEY  = os.path.join(PATH_AUDIT_KEY_DIR, "private.pem")
PATH_AUDIT_PUB_KEY   = os.path.join(PATH_AUDIT_KEY_DIR, "public.pem")

ENV_IGNORE_SELINUX   = "SPLUNK_IGNORE_SELINUX"


###
###  things called by bin/splunk, etc.
###


def checkXmlFiles(args, fromCLI):
  """
  Gathers all .xml files in path, recursively, and runs them through the
  minidom parser.
  """

  print "\tChecking configuration... ",; sys.stdout.flush()

  BLACKLIST = [
    {
      "condition": lambda root: os.path.split(root)[0] == os.path.join(comm.splunk_home, "etc", "apps"),
      "filter": lambda dir: dir in ("default", "local")
    },
  ]

  paramReq = ()
  paramOpt = ()
  comm.validateArgs(paramReq, paramOpt, args)

  retDict  = {}

  ################
  ################ BEGIN PART 1
  ################

  xmlErrs  = 0
  xmlFiles = []
  # path to search.
  dirPath  = os.path.join(comm.splunk_home, "etc")

  def filter_dirs(root, dirs):
    new_dirs = dirs
    for exclude in BLACKLIST:
      condition = exclude["condition"]
      filter_fn = exclude["filter"]
      if condition(root):
        new_dirs = filter(filter_fn, new_dirs)
        
    return new_dirs
        
  # run the cmd on appropriately sized subsets of xml files.
  for root, dirs, files in os.walk(dirPath, topdown=True):
    files[:] = filter(lambda x: x.endswith(".xml"), files)
    dirs[:] = filter_dirs(root, dirs)
    
    for filename in files:      
      file = os.path.join(root, filename)

      # should not start with "." (editor temp, hidden, etc) because dotfiles are lame
      # this is only enforced via this pre-flight message at the moment (4.2.2)
      if os.path.basename(file).startswith("."):
        logger.error("\nIgnored file '%s': filename begins with '.'\n", file)
        continue

      try:
        xml.dom.minidom.parse(file)
      except:
        value = sys.exc_info()[1]
        logger.error("Error while parsing '%s':\n %s\n", file, value)
        xmlErrs += 1

  ### all done, report/prompt now.

  if xmlErrs > 0:
    if not comm.prompt_user("\nThere were problems with the configuration files.\nWould you like to ignore these errors? [y/n]:"):
      raise cex.ParsingError, "Parsing error in configuration files."

  print "Done." 
  return retDict


def firstTimeRun(args, fromCLI):
  """
  All of our first time run checks that used to happen in the former bin/splunk shell script.
  Does any number of things, such as config migration, directory validation, and so on.  For
  the most up to date info, read the code.  It tends to be fairly well documented.
  """

  paramReq = (ARG_DRYRUN, ARG_FRESHINST,)
  paramOpt = (ARG_LOGFILE,)
  comm.validateArgs(paramReq, paramOpt, args)

  isFirstInstall = comm.getBoolValue(ARG_FRESHINST, args[ARG_FRESHINST])
  isDryRun = comm.getBoolValue(ARG_DRYRUN, args[ARG_DRYRUN])
  retDict  = {}

  # ...arg parsing done now.

  # NOTE:
  # none of the changes that are made in this function are subjected to isDryRun.
  # these things just have to be done - they're not considered to be migration.

  ##### if user doesn't have a ldap.conf, put our default in its place.
  if not os.path.exists(migration.PATH_LDAP_CONF):
    comm.copyItem(migration.PATH_LDAP_CONF_DEF, migration.PATH_LDAP_CONF)

  if not os.path.exists(PATH_AUDIT_PRIV_KEY) and not os.path.exists(PATH_AUDIT_PUB_KEY):
    kCmd = ["splunk", "createssl", "audit-keys"]
    kPriv, kPub, kDir = PATH_AUDIT_PRIV_KEY, PATH_AUDIT_PUB_KEY, PATH_AUDIT_KEY_DIR
    retCode = comm.runAndLog(kCmd + ["-p", kPriv, "-k", kPub, "-d", kDir])
    if 0 != retCode:
      raise cex.FilePath, "Could not create audit keys (returned %d)." % retCode

  try:    
    keyScript = comm.getConfKeyValue("distsearch", "tokenExchKeys", "genKeyScript" );
    keyCmdList = [os.path.expandvars(x.strip()) for x in keyScript.split(",") if len(x) > 0] # a,b,,d -> [a,b,d]
    pubFilename = comm.getConfKeyValue("distsearch", "tokenExchKeys", "publicKey" );
    privateFilename = comm.getConfKeyValue("distsearch", "tokenExchKeys", "privateKey" );
    certDir = comm.getConfKeyValue("distsearch", "tokenExchKeys", "certDir" )
    certDir = os.path.expandvars( certDir )
    privateFilename = os.path.join( certDir,privateFilename )
    pubFilename = os.path.join( certDir, pubFilename )
    if not ( os.path.exists( os.path.join( certDir,privateFilename ) ) or os.path.exists( os.path.join( certDir, pubFilename ) ) ):
      cmdList = keyCmdList + [ "-p", privateFilename, "-k", pubFilename,"-d", certDir ]
      success = comm.runAndLog( cmdList ) == 0
      if not success:
        logger.warn("Unable to generate distributed search keys."); #TK mgn 06/19/09
        raise cex.FilePath, "Unable to generate distributed search keys." #TK mgn 06/19/09
  except:
    logger.warn("Unable to generate distributed search keys."); #TK mgn 06/19/09
    raise 

  if isFirstInstall:
    ##### if user doesn't have a ui modules dir, put our default in its place. only run this in this block - otherwise,
    #     in an upgrade, we run the same code during migration and show an incorrect warning ("oh noes dir is missing").
    if not os.path.exists(migration.PATH_UI_MOD_ACTIVE):
      comm.moveItem(migration.PATH_UI_MOD_NEW, migration.PATH_UI_MOD_ACTIVE)
  ##### we're in an upgrade situation.
  else:
    ##### now do the actual migration (or fake it, if the user wants).
    #     upon faking, this function will throw an exception.
    if not ARG_LOGFILE in args:
      raise cex.ArgError, "Cannot migrate without the '%s' parameter." % ARG_LOGFILE
    migration.autoMigrate(args[ARG_LOGFILE], isDryRun)


  ##### FTR succeeded.  johnvey's never gonna have eggs. T_T

  # --- done w/ FTR, now i can has bucket?? ---
  return retDict


def preFlightChecks(args, fromCLI = False):
  paramReq = ()
  paramOpt = ()
  comm.validateArgs(paramReq, paramOpt, args)
  #
  checkPerms()
  index.importAllFlatFiles({}, fromCLI)
  checkSearchthing()
  checkSELinux()


###
###  things we call internally.
###

def checkPerms():
  """
  Ensures that we can write to the dirs we need to write to.
  """
  testFilename = "permsTest"
  testDirs = (
    comm.splunk_home,
    comm.splunk_db
  )
  for oneDir in testDirs:
    testPath = os.path.join(oneDir, testFilename)
    try:
      comm.touch(testPath)
    except IOError:
      raise cex.FilePath, "Splunk is unable to write to the directory '%s' and therefore will not run.  Please check for appropriate permissions on this directory and its contents as necessary." % oneDir
    os.remove(testPath)


def checkSearchthing():
  """
  Performs a locking test on the splunk_db dir.
  """
  retCode = comm.runAndLog(["locktest"], logStdout = False)
  if 0 != retCode:
    raise cex.FilePath, "Locking test failed on filesystem in path '%s' with code '%d'.  Please file a case online at http://www.splunk.com/page/submit_issue" % (comm.splunk_db, retCode)

def promptLicense():
  if not comm.isWindows: # windows will probably display its license in the installer.
    if os.path.exists(PATH_LICENSE_FILE):
      if sys.stdin.isatty():
        subprocess.call(["more", PATH_LICENSE_FILE]) # TODO: test this on dirs w/ spaces.  prob works fine.
      else:
        logger.info(open(PATH_LICENSE_FILE, 'r').read())
    else: # don't barf in dev envs
      comm.out("Could not find license file.")
    if not comm.prompt_user("Do you agree with this license? [y/n]: ", checkValidResponse = True):
      raise cex.InputError("License refused - exiting.")


def checkSELinux():
  if ENV_IGNORE_SELINUX in os.environ:
    comm.out("Skipping SELinux check (to enable this check, unset the '%s' environment variable)." % ENV_IGNORE_SELINUX)
  else:
    if os.path.exists(PATH_SELINUX_CONFIG):
      comm.out("\tChecking for SELinux.")
      if "enforcing" in comm.sed("^SELINUX=(.*)", "\\1", PATH_SELINUX_CONFIG):
        raise cex.ArgError, "Splunk will not run with SELinux enabled.\nIf you have adjusted Splunk's security level with chcon, you can bypass this check by setting the '%s' environment variable." % ENV_IGNORE_SELINUX
