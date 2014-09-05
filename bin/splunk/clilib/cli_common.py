#   Version 4.0
import __main__
import logging.handlers
import getpass, string, re, os, sys, copy, stat, socket, subprocess, time, traceback
import xml.etree.cElementTree as et
import lxml.etree as etree
import xml.dom.minidom
import httplib, shutil
from cStringIO import StringIO
from xml.sax import saxutils
import traceback
from control_exceptions import *
import splunk
from splunk.clilib import build_info

import logging
logging.getLogger('splunk.clilib.cli_common').addHandler(logging.NullHandler())
#This is evil but better than the circular dependancy between validate and cli_common
#TODO : _someone_ find clients of these methods and migrate them to validate
from validate import validateInput, _alphaNumIshPattern, checkBool 

# setup a custom logging level.  stuff that's more important than info,
# but not quite a warning.
logNoticeLevel = (logging.WARNING + logging.INFO) / 2
logging.addLevelName(logNoticeLevel, "NOTICE")
def loggerNotice(msg, *args, **kwargs):
  logging.log(logNoticeLevel, msg, *args, **kwargs) # basically a passthrough.
logging.notice = loggerNotice # allow for calling logging.notice("foo").

logger = logging.getLogger('splunk.clilib.cli_common')
logger.notice = logging.notice # allow for calling logger.notice("foo").

# when populated, this will be dict[file][stanza][key]=value
confSettings = {}


################################ IMPORTANT VARS // ################################

# these env vars are always required.  our caller always sets them.
splunk_home     = os.path.normpath(os.environ["SPLUNK_HOME"])
splunk_db       = os.path.normpath(os.environ["SPLUNK_DB"])

acceptLic  = False
answerYes  = False
isNoPrompt = False
isWindows  = ("win32" == sys.platform)
ninjaMode  = False
debugMode  = False

#SPL-23118
if isWindows:
   #pylint: disable=F0401
   import win32service
   import win32serviceutil

ENV_IS_TERMINAL = isWindows and "PROMPT" or "TERM"
KEY_SPLUNKD_SSL = "enableSplunkdSSL"
KEY_WEB_SSL     = "enableSplunkWebSSL"

isTerminal      = ENV_IS_TERMINAL in os.environ

_version     = None        #free|pro|unknown

_cronPattern        = "^[*0-9-/\-]+$"     # allows for */20, 1-2, 0, etc.
_portpattern        = '^\d+$'

SPLUNK_PY_PATH = os.path.dirname(splunk.__file__)

ERROR_AUTH     = "Authentication Failed"

################################ // IMPORTANT VARS ################################


# lots of functions needed by initialization things, declare them before setting up confSettings.

def bom_aware_readline(fileobj):
    atstart = (fileobj.tell() == 0)
    line = ""
    while True:
        l = fileobj.readline()
        if atstart:
            if len(l) > 2 and ord(l[0]) == 239 and ord(l[1]) == 187 and ord(l[2]) == 191:
                # UTF-8 BOM detected: skip it over
                l = l[3:]
            atstart = False
        # if line ends with \, append \n, then to the top of the loop to append the next line.
        if l.rstrip("\r\n").endswith("\\"):
          line += l.rstrip("\r\n")
          line += "\n"
        else:
          line += l
          break
    return line

def bom_aware_readlines(fileobj):
    lines = []
    while True:
        l = bom_aware_readline(fileobj)
        if l:
            lines.append(l)
        else:
            break
    return lines

# reads Sorkins .conf files into a dictionary of dictionaries
def readConfFile(path):
    if not len(path) > 0:
        return None
    
    settings = {}
    currStanza = None

    if not os.path.exists(path):
      # TODO audit consumers, then remove this file creation entirely, it's
      # deeply wrong.
      confdir = os.path.dirname(path)
      if not os.path.exists(confdir):
        os.makedirs(confdir)
      f = open(path, 'w')
    else:
      f = open(path, 'rb')
      lines = bom_aware_readlines(f)
      settings = readConfLines(lines)

    f.close()
    return settings

# takes a list of lines in conf file format, and splits them into dictionary (of stanzas), each of which is a dictionary of key values.
# the passed list of strings can come either from the simple file open foo in readConfFile, or the snazzier output of popen("btool foo list")
def readConfLines(lines) :
    currStanza = "default"
    settings   = {currStanza : {}}

    for line in lines:
      l = line.strip()
      if l.startswith("#") : continue
      if l.startswith('['):
          stanza = l.lstrip('[')
          endLoc = stanza.rfind(']')
          if endLoc >= 0:
            stanza = stanza[:endLoc]
          if stanza not in settings:
              settings[stanza] = {}
          currStanza = stanza
      elif line.find("=") > 0:
          # keys are assumed to have no '=' chars in them. Values are allowed to have one or more.
          (key, val) = l.split('=',1)
          key = key.strip()
          val = val.strip()
          settings[currStanza][key] = val
    return settings


def getMergedConf(confName):
  stdout = '%s' % getMergedConfRaw(confName) # how to make pylint believe it's a string
  return readConfLines(stdout.splitlines())


# FIXME(gba) Disabling 'Invalid name' because these methods were probably
#            named by a Java developer.
# pylint: disable=C0103
def getMergedConfRaw(confName):
    """Collects configuration values using btool.

    Test
    ====
        >>> a = getMergedConfRaw('server')
        >>> 'splunk' in a
        True
        >>> b = getMergedConfRaw('djhans925')
        >>> b == ''
        True

    Operation
    =========
        @param confName: Name of the configuration to collect.
                         Normally the name of the configuration file,
                         sans '.conf'.
        @type confName: string
        @return: Configuration values from 'btool list' command.
        @rtype: string
    """
    try:
        proc = subprocess.Popen(['btool', confName, 'list'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc_out, proc_err = proc.communicate()
    except OSError, ex:
        logger.warn("Failed merge %s.conf: "
                "subprocess.Popen for Btool had a problem\n" % confName)
        logger.debug("btool raised an Exception: '%s'" % ex)

        # SPL-37439 If we're on windows, exit, otherwise raise.
        if isWindows:
            sys.exit()
        else:
            raise

    # FIXME(gba) Maybe we'd rather fail if btool returns something in stderr?
    if not proc_err == '':
        logger.warn("btool returned something in stderr: '%s'" % proc_err)

    return proc_out


# cache some config files that launcher generates for us.  for a list of files
# that are valid to access here, see launcher/main.c.
# - we can't run btool (anything, really) from multithreaded python.
# - aix has further difficulties: python bug #1731717.
# therefore the UI gets its settings from merged .conf files created by
# launcher.
def cacheConfFile(confName):
  global confSettings
  if confName in confSettings:
    return # do nothing if cache exists.

  # cli.py sets this value to False as soon as it loads.  the CLI doesn't rely
  # on the cached files because:
  # - it doesn't have to.
  # - the system user running the CLI command may not have permission to write
  #   to the merged config file location.
  # - concurrent CLI invocations would clobber each other's merged files.

  useCachedConfigs = (("useCachedConfigs" in dir(__main__)) and (__main__.useCachedConfigs,) or (True,))[0]
  # this will not always eval to True; see http://www.diveintopython.net/power_of_introspection/and_or.html#d0e9975, Example 4.18

  mergedPath = os.path.join(splunk_home, "var", "run", "splunk", "merged", confName + ".conf")
  if useCachedConfigs and os.path.exists(mergedPath) and os.path.getsize(mergedPath) > 0:
    logger.debug("Preloading from '%s'." % mergedPath)
    confSettings[confName] = readConfFile(mergedPath)
  else:
    logger.debug("Running btool for '%s.conf'." % confName)
    confSettings[confName] = getMergedConf(confName)


def getConfStanza(confName, stanza):
  cacheConfFile(confName)
  try:
    return confSettings[confName][stanza]
  except KeyError:
    raise ParsingError, "no '%s' stanza exists in %s.conf.  Your configuration may be corrupt or may require a restart." % (stanza, confName)


def getConfKeyValue(confName, stanza, key):
  stanza = getConfStanza(confName, stanza)
  try:
    return stanza[key]
  except KeyError:
    raise ParsingError, "no '%s' key exists in the '%s' stanza in %s.conf.  Your configuration may be corrupt or may require a restart." % (key, stanza, confName)

def getServerConfKeyValue(key):
  return getConfKeyValue("server", "sslConfig", key)
def getWebConfKeyValue(key):
  return getConfKeyValue("web", "settings", key)


_mgmtUri = None # do not access this directly.  needed for setURI().
def getMgmtUri():
  global _mgmtUri
  if not _mgmtUri:
    # this helps us avoid 2 btool invocations (server & web) below.
    if "SPLUNKD_URI" in os.environ:
      _mgmtUri = os.environ["SPLUNKD_URI"]
    else:
      # TODO: attempt getting from env.
      isMgmtSSL  = getServerConfKeyValue(KEY_SPLUNKD_SSL).lower() == "true"
      mgmtPrefix = isMgmtSSL and "https://" or "http://"
      _mgmtUri    = mgmtPrefix + getWebConfKeyValue("mgmtHostPort")
      if( "SPLUNK_BINDIP" in os.environ ):
        bip = os.environ["SPLUNK_BINDIP"]
        if bip.find(":") >= 0:
          bip = "[" + bip + "]"
        _mgmtUri = mgmtPrefix + bip + _mgmtUri[_mgmtUri.rfind(":"):]
  return _mgmtUri

def getWebUri():
  isWebSSL  = getWebConfKeyValue(KEY_WEB_SSL).lower() == "true"
  webPrefix = isWebSSL and "https://" or "http://"
  webUri    = webPrefix
  if( "SPLUNK_BINDIP" in os.environ ):
    bip = os.environ["SPLUNK_BINDIP"]
    if bip.find(":") >= 0:
      bip = "[" + bip + "]"
    webUri  = webUri + bip
  else:
    webUri  = webUri + "127.0.0.1"
  webUri = webUri + ":" + getWebConfKeyValue("httpport")
  return webUri


def setURI(uri):
  # TODO PERFORM LOTS OF VALIDATION HERE TODO
  # (empty, no host, no port, invalid chars, etc)
  # this is just a simple placeholder
  global _mgmtUri

  #SPL-16084
  #the uri needs to be in the format: [http|https]://[name of server]:[port]
  try:
    protocol, rest = uri.split(':', 1)
    if not protocol in ['https', 'http']:
      raise ArgError, 'uri needs to be in the format [http|https]://[name of server]:[port]'
    elif not (rest[:2] == '//' and rest[2:]):
      raise ArgError, 'uri needs to be in the format [http|https]://[name of server]:[port]'
    else:
      port = rest[rest.rfind(":")+1:]
      try:
        int(port)
      except ValueError:
        raise ArgError, 'uri needs to be in the format [http|https]://[name of server]:[port]'
  except:
    raise ArgError, 'uri needs to be in the format [http|https]://[name of server]:[port]'

  _mgmtUri = uri


# TODO i forget exactly what this is being used for at this moment, but it should prob be folded into the new logging stuff. FIXME
def out(output):
  if ninjaMode:
    pass
  else:
    logger.info(output)

###
# returns an config.xml-style <pipeline/> node
# with the given name, 
# included is a <processor/> node with given name and pluginname
def makepipe(name, proc, plug, outQueue, children = None):

	xmlstring = "<pipeline name=\"%s\" type=\"startup\">\n\t<processor name=\"%s\" plugin=\"%s\">\n\t\t<config>\n\t\t</config>\n\t</processor>\n\n\t<processor name=\"sendOut\" plugin=\"queueoutputprocessor\">\n\t\t<config>\n\t\t\t<queueName>%s</queueName>\n\t\t</config>\n\t</processor>\n</pipeline>" % (name, proc, plug, outQueue)

	dom = xml.dom.minidom.parseString(xmlstring)

	# ref to the <pipeline/> node
	pipenodeList = dom.getElementsByTagName('pipeline')
	if len(pipenodeList) > 0:
		pipenode = pipenodeList[0]
	else:
		raise ConfigError('Problem creating pipeline.') 

	# ref to the <config/> node
	confignodeList = dom.getElementsByTagName('config')
	if len(confignodeList) > 0:
		confignode = confignodeList[0]
	else:
		raise ConfigError('Problem creating childnode in <config/>.') 

	# if we are given a list of nodes to put in <config/>,
	# create and append them now
	if not children is None:
		for child in children:
			# dont create nodes w/ 0-len tagnames
			if not len(child) > 0:
				continue	
			newnode = dom.createElement(child)
			confignode.appendChild(dom.createTextNode('\t'))
			confignode.appendChild(newnode)
			confignode.appendChild(dom.createTextNode('\n\t\t'))

	return pipenode

def print_help( command, help_dict ):
    help_text = "\nAvailable " + command +" commands:\n"
    for i in help_dict.keys():
	cmd = i
	msg = help_dict[i]
	help_text = help_text + "\t" + cmd +  "  :  " + msg + "\n"
        logger.info("") # TODO: this ... just doesn't make sense.  why all the newlines?  should be looked into. FIXME
	
    help_text = help_text
    
    return help_text

def checkargs( argumentlist, arg):
    for x in argumentlist.keys():
	if cmp(x, arg) == 0:
	    return 0

    return 1


def restCall(args, fromCLI):
  paramsReq = ("path",)
  paramsOpt = () # accepts arbitrary...
  validateArgs(paramsReq, paramsOpt, args, exceptionOnUnknownArgs = False)

  PREFIX_GET  = "get:"
  PREFIX_POST = "post:"

  uriPath = args.pop("path")
  authStr  = "trans ams rule"
  if "authstr" in args: # not required for certain endpoints.
    authStr = args.pop("authstr")

  getArgs  = {}
  postArgs = {}
  for arg, val in args.items():
    if arg.startswith(PREFIX_GET):
      getArgs[arg.replace(PREFIX_GET, "", 1)]  = val
    elif arg.startswith(PREFIX_POST):
      postArgs[arg.replace(PREFIX_POST, "", 1)] = val
  for getArg in getArgs:
    args.pop(PREFIX_GET + getArg)
  for postArg in postArgs:
    args.pop(PREFIX_POST + postArg)

  method = "GET" # automatically changed to post by simpleRequest as necessary.
  if "method" in args:
    method = args.pop("method")

  if len(args) > 0:
    raise ArgError, "The following parameters are unrecognized: %s." % str.join(", ", args.keys())

  logger.debug("Will attempt REST call to: %s with GET args:\n  %s\nand POST args:\n  %s\n with method %s.\n"
      % (uriPath, getArgs, postArgs, method))

  import splunk.rest
  response, content = splunk.rest.simpleRequest(uriPath, sessionKey=authStr, getargs=getArgs, postargs=postArgs, method=method, rawResult=True)
  logger.debug("Server response: %s.\n" % str(response))
  # if not a http success status code...
  if response.status < 200 or response.status > 299:
    from splunk.rcUtils import InvalidStatusCodeError # don't like. FIXME
    raise InvalidStatusCodeError, "Server returned HTTP status %d.  See error below:\n%s" % (response.status, content) # stderr.
  # otherwise print as normal.
  logger.notice("HTTP Status: %d." % response.status)   # stderr.
  logger.notice("Content:")                             # stderr.
  logger.info(content)                                  # stdout.


def checkConfigFile(path_to_config):
	""" 
	Checks to see if the given config file exists:

	PRE:
	path_to_config is a sane path to config file

	POST:
	raise exception on failure; return false on empty path
	return true on valid
	"""

	if not len(path_to_config) > 0:
		return False

	if not os.path.exists(path_to_config):
		raise FilePath('Missing config file?' + path_to_config) 
	# on okay, return a true
	return True



##################################################################

# given a sane path,
# return a minidom parsed DOM
def loadDOM(path):
    # check to make sure the path is okay
    if not os.path.exists(path):
        raise FilePath, "File does not exist: '%s'" % path
    if not os.path.isfile(path):
        raise FileType, "'%s' is not a regular file" % path
    if not os.access(path, os.R_OK):
        raise FileAccess, "'%s' is not accessible by this user." % path

    # check for and parse the given xml file
    checkConfigFile(path)
    dom  = xml.dom.minidom.parse(path)

    return dom

# given a path we can write to,
# write a minidom dumped XML document to a file
def saveDOM(dom, path):
    # write the dom out to config file
    outfile = None
    try:
        outfile = file(path, 'w+')
        outfile.write(dom.toxml(encoding=None))
        outfile.write('\n')
    finally:
        outfile.close()


def overlayDOM(srcDOM, dstDOM):
  """
  This takes two xml.dom.minidom objects, and for any tags found in the source,
  overrides the corresponding tag values in the destination.
  This does not add to the dest any NEW tags that are in the source, nor does it
  respect any hierarchy - the latter meaning that this should only be used for
  unique non-hierarchical tags - but this servers our purposes just fine for now.
  Returns the new, overlaid dom.
  """
  newDOM = copy.deepcopy(dstDOM)
  for userItem in srcDOM.childNodes: # all such nodes
    if userItem.hasChildNodes(): # this must be a <tag>with a child</tag>
      # are there any default tags with this name?
      oldItems = newDOM.getElementsByTagName(userItem.nodeName)
      if len(oldItems) > 0:
        oldItem = oldItems[0] # should only be one such tag - use the first.
        # finally, override the default value with the custom user value
        oldItem.firstChild.nodeValue = userItem.firstChild.nodeValue
  return newDOM


##################################################################


# removes all files and dirs under dirname, excluding dirname
def remove_dirs(dirname):
    for root, dirs, files in os.walk(dirname, topdown=False):
        for name in files:
            os.remove(os.path.join(root, name))
        for name in dirs:
            path = os.path.join(root, name)
            if os.path.islink(path): # symlink
              os.remove(path)
            else:
              os.rmdir(path)

# removes all files and dirs under dirname including dirname
def remove_tree(dirname):
    shutil.rmtree(dirname)

def remove_file(filename):
    os.remove(filename)


def errorIfNoPrompt(question):
  if isNoPrompt:
    logger.info(question)
    raise ArgError("Exiting because user requested no prompting.")


# for prompt_user
PROMPT_CONTINUE = "Are you sure you want to continue [y/N]? "

# Asks the user a yes or no question
# TODO: get rid of the bool after making sure all users are safe for this behavior.
def prompt_user(question = PROMPT_CONTINUE, checkValidResponse = False):
  if answerYes:
    logger.info("%s y" % question)
    return True
  #
  errorIfNoPrompt(question)
  #
  value = raw_input( question ).strip()
  if checkValidResponse:
    while True:
      if not value.lower() in ('y', 'n', 'word son'):
        logger.error("Please answer with either 'y' or 'n'.")
        value = raw_input( question ).strip()
      else:
        break
  return value.lower() in ('y', 'word son')


def promptPassword(question):
  """
  A safer getpass.getpass().  Prompts users, but doesn't throw an IOError exception if 
  if stdin is closed.  Instead throws our own PipeIOError, which the CLI
  will handle appropriately.  We can't use normal IOErrors because the CLI will print
  out the stack trace for them, which is totally unnecessary here.
  """
  errorIfNoPrompt(question)
  # check this, cuz the following command can cause an exception:
  #   echo -e 'a\nb\nc' | splunk add user foo -full-name foo -role foo
  if not sys.stdin.isatty():
    raise PipeIOError, "Cannot prompt for password, stdin appears to be a pipe."
  try:
    if sys.platform.startswith('sunos'):
       #to prevent echoing
       userInput = getpass.getpass(question, sys.stderr)
    else:
       userInput = getpass.getpass(question)
  except IOError, e:
    raise PipeIOError, "Could not get password due to: %s." % e.strerror
  return userInput


def isLocalSplunkdUpForWindows():
   """
   flavour of isLocalSplunkdUp that works for windows - SPL-23118
   """

   running = True

   try:
      #check the status of the appropriate splunkd service i.e. splunkd or splunkd-preview or splunkd-beta etc
      status = win32serviceutil.QueryServiceStatus(getSplunkdServiceName())
      if status[1] not in [win32service.SERVICE_RUNNING, win32service.SERVICE_STOP_PENDING]:
         running = False
   except Exception, e:
      running = False

   return running

def isLocalSplunkdUp():
        """
        ChecKS whether a _local_ splunkd is up, through the pid file.  Returns boolean.
        """
        #SPL-23118
        if isWindows:
           return isLocalSplunkdUpForWindows()
        else:
           running = True
           pid_file = os.path.join(splunk_home, "var", "run", "splunk", "splunkd.pid")

           # Make sure pidfile exists
           try:
                   FILE = open(pid_file, "r")
                   pid = FILE.readline()
           except:
                   running = False

           # if it does, then make sure pid is running
           if running:
                   try:
                           val = os.kill(int(pid), 0)
                   except:
                           running = False

           return running


def validateArgs(required, optional, argList, exceptionOnUnknownArgs=True):
  """
  Used for verifying that all arguments provided are expected, and that any required args
  are present.  Takes a list of required args, a list of optional args, and the dictionary
  of args/values that was passed into the calling function.    If required args are
  missing, or if an unknown arg is listed, raises an exception.
  """
  removeList = []
  reqCopy = list(copy.deepcopy(required)) # list() in case we're passed a tuple..
  argCopy = copy.deepcopy(argList)
  # check every possible arg and make sure that they're all lowercase.  makes things easier.
  for possArg in required + optional:
    if possArg != possArg.lower():
      raise ArgError, "The argument key '%s' should be defined in all lowercase.  This is programmer error." % possArg
  # iterate all required args and record each one that's found in the dict.
  # don't actually remove the mathching args here, will ruin our loop otherwise.
  for arg in reqCopy:
    if arg in argCopy.keys():
      removeList.append(arg)
      argCopy.pop(arg)
  # NOW let's remove those required args - leaves us with any missing required args
  for item in removeList:
    reqCopy.remove(item)
  # and now remove matching _optional_ args from the dict
  for arg in optional:
    if arg in argCopy.keys():
      argCopy.pop(arg)
  # if every item hasn't been deleted from the required list, some of them weren't passed in.
  # also, if anything is left in the passed in dict, then some of them weren't valid.
  if len(reqCopy) > 0:
    raise ArgError, "The following required parameters have not been specified: %s." % str.join(", ", reqCopy)
  elif (exceptionOnUnknownArgs and len(argCopy) > 0):
    raise ArgError, "The following parameters are invalid: %s." % str.join(", ", argCopy.keys())
  else:
    # now that we know the actual arg names are correct, let's make sure none of them are empty
    for key, val in argList.items():
      if val == None or (val == "" and key != "authstr"):
        raise ArgError, "Error: The value passed in for the '%s' argument is empty." % key
    return True # is there any use to this? will be in a try block anyway...

def getAnonArgs(argList):
  listToReturn = []
  if not isinstance(argList, dict):
    raise ArgError, "Non-dictionary passed to validateAnonArgs (type is really: %s)" % type(argList)
  numArgs = len(argList)
  for i in range(0, numArgs):
    if not i in argList:
      raise ParsingError, "Anonymous/unnamed argument dictionary is not well formed.  Couldn't find key %d in dict of length %d." % (i, numArgs)
    listToReturn.append(argList[i])
  return listToReturn

def checkValidFileEAICLI(path):
   """
   version of this function that does not use invokeAPI stuff...for he new CLI
   """
   
   if not os.path.isabs(path):
      logger.error("Path is not an absolute path.")
      raise IOError, "Path is not an absolute path." 
   elif not os.path.isfile(path):
      logger.error("File path does not exist.")
      raise IOError, "File path does not exist."
   elif not os.access(path, os.R_OK):
      logger.error("File path not readable.")
      raise IOError, "File path not readable."
   elif not os.path.isfile(path):
      logger.error("Path is not a valid file.")
      raise IOError, "Path is not a valid file."


def isYes(somestring):
    # possible affirmative options
    yesSet = [
        "yes",
        "y",
        "1",
        "true",
        "on",
        "enable",
        "enabled",
    ]

    # possible negative options
    noSet = [
        "no",
        "n",
        "0",
        "false",
        "off",
        "disable",
        "disabled",
    ]
    
    # normalize the string
    teststr = somestring.strip().lower()

    # test for positive/negative,
    # raise exception on unknowns
    if teststr in yesSet:
        return True
    elif teststr in noSet:
        return False
    else:
        raise ArgError, 'invalid input to isYes()'

def getBoolValue(argName, argVal):
  argStr = str(argVal).lower()
  if argStr == "true" or argStr == "1":
    return True
  elif argStr == "false" or argStr == "0":
    return False
  else:
    raise ArgError, "Value for option '%s' must be 'true' or 'false' (got '%s')." % (argName, argVal)

def requireSplunkdDown():
  if isLocalSplunkdUp():
    raise ServerState, "This command requires splunkd to be stopped before running.  Please run 'splunk stop' and try again."


def skipConfirm(args):
  """
  determine if the user is explicitly using the -f option to force
  relocated here from clean.py
  """
  skip_confirmation = False
  if "force" in args.keys():
    # this condition should be pretty unnecessary...
    if isinstance(args["force"], str):
      if args["force"].lower() == "-f":
        skip_confirmation = True
      else:
        raise ArgError, "The value '%s' is not a valid force argument." % args["force"]
    else:
      if args["force"] == True: # don't one-line this - may not necessarily be a bool
        skip_confirmation = True

  return skip_confirmation
        

##########################################
# properties stuff


def flatDOMToDict(dom):
  """
  Takes an xml.dom.minidom element object and converts it to a dictionary.  Note
  that this will ONLY work on non-hierarchical data.  In other words, this will
  only convert the children of this node, and their data nodes - no child nodes
  two levels deep.

  Expected data sample: <root><child1>data1</child1><child2>data2</chilhd2></root>
  """
  valueDict = {}
  if dom.hasChildNodes():
    for child in dom.childNodes: # child1, child2, etc from above.
      if not isinstance(child, xml.dom.minidom.Text): # ugh whitespace
        if 1 == len(child.childNodes): # do we have data1, data2...?  make sure there's only one.
          valueDict[child.tagName] = child.firstChild.data
        else: # otherwise assume there's multiple sub-children, or no data - treat both the same.
          valueDict[child.tagName] = ""
  return valueDict


def flatDictToXML(src):
  """
  Does sorta the opposite of flatDOMToDict - takes a single level dictionary and
  returns an xml string with all the dict entries turned into tags & values.
  There is no root node.  To turn this into a valid dom object, you would have
  to wrap it in a node such as <root>...</root>, and pass the resulting string
  to xml.dom.minidom.parseString(...).
  """
  xmlStr = ""
  for key, val in src.items():
    xmlStr = "%s<%s>%s</%s>" % (xmlStr, key, val, key)
  return xmlStr

######################################
def getVersion():
  global _version
  if not _version: 
    info = getLicenseInfo()
    if "isFree" in info and info["isFree"]:
      #Splunkd must identify itself as not free
      #UGH
      _version = checkBool( "isFree", info["isFree"] ) and "free" or "pro" 
    else:
      _version = "free"
  return str(_version)

def isProVersion():
  try:
    status = (getVersion() == "pro")
  except ServerConnectionException:
    raise ServerState("\n\tSplunk is not running, and it must be for this operation.  \n\tTo start splunk, run \"splunk start\". For more help, use \"splunk help\".\n")
  return status

def getLicenseInfo():
  import splunk.entity # avoid circ dep
  # set this as a default since getEntity doesn't take proto/host/prrt just yet...
  splunk.mergeHostPath(getMgmtUri(), saveAsDefault=True)
  retDict = splunk.entity.getEntity("server", "info")
  return retDict

##############################################
# local filesystem stuff.
##############################################


def copyItem(src, dst, dryRun = False):
  """
  Copies a file via shutil.copy.  If dryRun is True, doesn't copy the file - only says that it would have done so.
  """
  logger.notice(((dryRun and "Would copy" or "Copying") + " '%s' to '%s'.") % (src, dst))
  if not dryRun:
    shutil.copy(src, dst)

def moveItem(src, dst, dryRun = False):
  """
  Moves a file via shutil.move.  If dryRun is True, doesn't move the file - only says that it would have done so.
  """
  logger.notice(((dryRun and "Would move" or "Moving") + " '%s' to '%s'.") % (src, dst))
  if not dryRun:
    ensureDeletable(src)
    shutil.move(src, dst)

def removeItem(path, dryRun = False):
  """
  Deletes a file or a directory, recursively if necessary. If dryRun is True,
  just prints out what would be deleted.
  """
  logger.notice(((dryRun and "Would delete" or "Deleting") + " '%s'.") % path)
  if not dryRun:
      ensureDeletable(path)
      if os.path.isdir(path):
          shutil.rmtree(path)
      else:
          os.remove(path)

def mkdirItem(dir, dryRun = False):
  """
  Creates a directory. If dryRun is True, just prints out the directory that
  would be created.
  """
  logger.notice(((dryRun and "Would create" or "Creating") + " '%s'.") % dir)
  if not dryRun:
    os.mkdir(dir)

def ensureDeletable(path):
  """
  Try and remove any read-only attributes on a file or dir, recursively.  This
  is not a problem on Unix generally, but on Windows, files that are shipped
  read-only need to have their attrib stripped before using python utils to
  delete them.
  """
  if not os.path.exists(path):
    return
  pathList = os.path.isdir(path) and recursiveDir(path) or [path]
  for oneItem in pathList:
    # believe it or not, this actually removes the read-only flag in windows.
    os.chmod(oneItem, os.stat(oneItem).st_mode | stat.S_IWRITE)

def mergeDirsWorker(src, dst, dryRun):
    try:
        # In case we don't have permission to truncate the
        # file, just remove it preemptively.
        if os.path.lexists(dst):
            removeItem(dst, dryRun)
        copyItem(src, dst, dryRun)
    except Exception, e:
        # A file's parent directory may be missing if a pre-existing
        # regular file prevents mergeDirs from creating a directory.
        logger.warn("Cannot copy %s to %s" % (src, dst))
        logger.exception(e)
        raise

def mergeDirs(src_base, dst_base, dryRun = False, copier = mergeDirsWorker):
    """
    Copy the contents of src_base into dst_base, overwriting any existing files
    in dst_base, i.e. 'cp -ry src_base/* dst_base/'.
    """
    cwd = os.getcwd()
    os.chdir(src_base)
    for dirpath, dirnames, filenames in os.walk('.'):
        for dir in dirnames:
            dst = os.path.normpath(os.path.join(dst_base, dirpath, dir))
            if not os.path.exists(dst):
                mkdirItem(dst, dryRun)
            elif not os.path.isdir(dst):
                logger.warn("Cannot create directory: Existing file: %s" % dst)
        for file in filenames:
            src = os.path.normpath(os.path.join(src_base, dirpath, file))
            dst = os.path.normpath(os.path.join(dst_base, dirpath, file))
            copier(src, dst, dryRun)
    os.chdir(cwd)


def recursiveDir(dirPath):
  """
  Gives a full dir listing of a given dir, recursively.  Lists files & subdirs,
  even if they're empty.
  
  Essentially what "find /some/path" would give you in a Unixy environment.
  """

  if not os.path.isdir(dirPath):
    raise FilePath, "Cannot list path '%s' - is not a dir." % dirPath

  itemList = []
  for oneDir, itsSubdirs, itsFiles in os.walk(dirPath):
    itemList.append(oneDir)
    for oneFile in itsFiles:
      itemList.append(os.path.join(oneDir, oneFile))
  return itemList


def findFiles(dirPath, pattern, caseSens = True, minBytes = 0, skipdir_pattern=None):
  """
  Takes a directory and a regular expression.
  Default case-sensitive, overridden with caseSens=False.
  Default no minimum filesize, overriden with minBytes=<bytes>.
  Returns all files that match.
  """
  results = []
  if caseSens:
    regex   = re.compile(pattern) # TODO: error-check?
  else:
    regex   = re.compile(pattern, re.IGNORECASE) # TODO: error-check?
  
  skip_regex = None
  if skipdir_pattern:
    skip_regex = re.compile(skipdir_pattern)

  def checkMatch(filePath):                                                                        

    didMatchPath = regex.search(filePath)
    if not didMatchPath:
      return None

    # if there is a problem, warn but don't skip the file
    try:
      fileSize = os.stat(filePath).st_size      
    except (OSError), (errno, strerror):
      logger.warn("\nCannot get size for file %s: [Errno %s] %s" % (filePath, errno, strerror))
      return True
    except Exception as e:
      # just in case some weird thing happens, capture the exception
      # not sure True is the best here, but maintains existing behavior
      logger.error("\nError checking file %s\n" % filePath)
      logger.error(traceback.format_exception(*sys.exc_info()))
      return True

    matched = ((minBytes < 1) and True or fileSize >= minBytes)
    return matched    

  for dir, subdirs, files in os.walk(dirPath):
    # os.walk requires this funny pattern, that you modify dirs in place to skip
    # traversing to subdirs. 
    if skip_regex:
      subdirs[:] = filter(lambda sd: not skip_regex.search(os.path.join(dir, sd)), subdirs)
    results.extend(filter(checkMatch, [os.path.join(dir, oneFile) for oneFile in files]))
  return results

 
def grep(pattern, filepath):
  """
  It's like grep.  We need to write our own for Windows.
  Does not do multiline matches.
  Returns tuple of matching lines.  Empty tuple if no matches.
  """
  matches = []
  # TODO: catch exception here
  regex   = re.compile(pattern)
  inFile = open(filepath, 'r')
  while True:
    line = bom_aware_readline(inFile)
    if 0 == len(line): # EOF
      break
    result = regex.search(line)
    if None != result: # matched something in the line.
      # clean up before adding, readline() preserves newlines.
      matches.append(line.rstrip("\r\n"))
  inFile.close()
  return matches


def sed(searchFor, replaceWith, filepath, inPlace = False):
  """
  It's like sed.  We need to write our own for Windows.  Does not do multiline
  fanciness.  Or anything too fancy, really.  sed-like options will be
  implemented as needed.

  if inPlace is False (default), returns list w/ matching results.  Non-matching
  results are not included.

  If inPlace is True, initially writes to a .tmp file, then replaces the
  original with the .tmp file.  Effectively modifies file in-place and returns
  an empty list.
  """
  results = []
  if not os.path.isfile(filepath):
    raise ArgError, "sed requires that passed-in argument '%s' is a valid file." % filepath

  # TODO: catch exception here
  regex   = re.compile(searchFor)

  inFile  = open(filepath, 'r')
  if inPlace:
    tmpPath = filepath + ".tmp"
    outFile = open(tmpPath,  'w')
  while True:
    line = bom_aware_readline(inFile)
    if 0 == len(line): # EOF
      break
    (postRegex, numSubs) = regex.subn(replaceWith, line)
    if inPlace:
      outFile.write(postRegex) # we'll leave the newlines here.
    else:
      if numSubs > 0: # line matched
        # clean up before adding, readline() preserves newlines.
        results.append(postRegex.rstrip("\r\n"))

  inFile.close()
  if inPlace:
    outFile.close()
    shutil.move(tmpPath, filepath)

  return results


def touch(filepath):
  """
  Creates a 0 byte file, or updates the timestamp of an existing file, now a
  little bit more like the Unix utility 'touch'.
  """
  if os.path.exists(filepath):
    os.utime(filepath, None)
  else:
    open(filepath, 'w').close()


# writes a dictionary of dicts to a Sorkin .conf file
def writeConfFile(path, stanzaDict):
    if not len(path) > 0:
        return None

    if not len(stanzaDict) > 0:
        return None

    f = open(path, 'w')

    stanzaList = stanzaDict.keys()
    stanzaList.sort()

    # print the default stanza first - it has no header.
    if "default" in stanzaList:
        f.write("[%s]\n" % "default")
        for key,val in stanzaDict["default"].items():
            f.write("%s = %s\n" % (key, val) )
        f.write("\n")
        stanzaList.remove("default")

    for stanza in stanzaList:
        f.write("[%s]\n" % stanza)
        for key,val in stanzaDict[stanza].items():
            f.write("%s = %s\n" % (key, val) )
        f.write("\n")

    f.close()
    return True


def runAndLog(cmdList, logStdout = True, logStderr = True):
  """
  Rums a given command (given as a list of name and args) and logs any output.
  Returns return code.
  """
  proc = subprocess.Popen(cmdList, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  procOut, procErr = proc.communicate()
  if logStdout and len(procOut) > 0:
    # remove final newline because logger.info already appends
    if procOut[-1] == '\n': procOut = procOut[:-1]
    logger.info(procOut)
  if logStderr and len(procErr) > 0:
    #SPL-20646
    logger.error(procErr)
  return proc.returncode

#######################################################


def resolveHostname(hostname):
  """
  Look up the ip address for a given hostname, and catch some of the common errors..
  """
  try:
    ip = socket.gethostbyname(hostname)
  except socket.gaierror, e:
    if e[0] == socket.EAI_NONAME:
      raise ArgError, "Could not lookup IP address for host '%s'." % hostname
    else:
      raise
  return ip


#######################################################


###########################################################
# stuff that came from ui-land

def makeXMLSafe(escapeMe) :
    escapeMe = escapeMe.replace("&","&amp;")
    escapeMe = escapeMe.replace("<","&lt;")
    escapeMe = escapeMe.replace(">","&gt;")
    escapeMe = escapeMe.replace("\"","&quot;")
    escapeMe = escapeMe.replace("'","&apos;")
    return escapeMe


def isIterable(object) :
    try : 
        iter(object)
    except TypeError, e:
        return False
    return True



###########################################################
# get OS-specific location of temporary directory

if sys.platform == 'win32':
    def tmpDir():
        #pylint: disable=F0401
        import win32api
        return win32api.GetTempPath()
else:
    def tmpDir():
        result = os.environ.get("TMPDIR")
        if result is None or result == "":
            result = "/tmp" # for anyone grepping - this does NOT need to be made OS independent.
        return result


def uploadDir():
  return os.path.join(splunk_home, 'var', 'run', 'splunk', 'upload')


###########################################################
# logging utilities/classes.


class FilterThreshold(logging.Filter):
  def __init__(self, normal):
    logging.Filter.__init__(self)
    if normal:
      self.filter = lambda record: record.levelno == logging.INFO
    else:
      self.filter = lambda record: record.levelno != logging.INFO


def newLogHandler(stream, isDebug, normal, filter = True):
  if normal:
    fmt = "%(message)s"
  else:
    fmt = isDebug and "%(levelname)s (%(module)s) %(message)s" or "%(message)s"
  logHandler = logging.StreamHandler(stream)
  logHandler.setFormatter(logging.Formatter(fmt))
  if filter:
    logHandler.addFilter(FilterThreshold(normal))
  return logHandler

# example usage: 
#
#       id_user_map = id2userMapFromPasswdFile( "/opt/splunk/etc/passwd" )
#       for id,name in id_user_map.items():
#               print "user with id="+id+" has username=" + name
####
def id2userMapFromPasswdFile(path):
        retval = {}
        if not os.path.isfile( path ):
                logger.warn( 'file ' +path+ ' does not exist' )
                return {}
        fin = open(path, "r")
        line = fin.readline()
        passwd_line_checker = re.compile( "^\d+:\S+:" );
        while line:
                if passwd_line_checker.search( line ) :
                        tokens = line.split(":")
                        if ( len(tokens) >= 2 ):
                                retval[ tokens[0] ] = tokens[1]                
                        else:
                                logger.warn( 'skipping due to len(token) ' + line + ' ' + str(len(tokens)) )
                else:
                        logger.warn( 'skipping due to regex check ' + line )
                line = fin.readline()
        return retval

###########################################################
# bucket operations
  
def rollHotBuckets(args, fromCLI):
  """
  Roll the hot buckets to warm for the specified index
  """
  
  paramsReq = ("index",)
  paramsOpt = ("force",) 
  validateArgs(paramsReq, paramsOpt, args, exceptionOnUnknownArgs = False)

  indexName = args.pop("index")
  logger.notice("Rolling hot buckets to warm for index '%s'." % indexName)

  # set this here so force (if provided) can perform requested action
  confirmed = True
    
  if fromCLI:
    # first, does that index exist?
    index_conf = getMergedConf('indexes')
    if not indexName in index_conf:
      logger.info("There is no index %s configured." % indexName)
      return

    skip_confirmation = skipConfirm(args)
    if not skip_confirmation:
      logger.info("This action will roll your hot buckets to warm; it cannot be undone.")
      confirmed = prompt_user()

    if confirmed:
      # make a copy of the dict so we can add the correct endpoint path
      myArgs = args.copy()
      endpointPath = "/data/indexes/%s/roll-hot-buckets" % indexName
      myArgs["path"] = endpointPath

      # done with this now, remove if exists. restCall doesn't like it
      if "force" in args:
        del myArgs["force"]
            
      # call the endpoint
      # note splunkd validates index name but doesn't propagate any errors back yet
      restCall(myArgs, fromCLI)

      logger.notice("Hot to warm roll request submitted for execution.")
            
    else:
      logger.notice("Hot to warm roll cancelled")
  
  return True
                                                                                              

def rebuildMetadata(args, fromCLI):
  """
  Rebuild the *.data files for the specified index via rest
  """
  
  paramsReq = ("index",)
  paramsOpt = ("force",)
  validateArgs(paramsReq, paramsOpt, args, exceptionOnUnknownArgs = False)
  
  indexName = args.pop("index")
  logger.notice("Rebuilding metadata for index '%s'." % indexName)
  
  # set this here so force (if provided) can perform requested action
  confirmed = True
  
  if fromCLI:
    # first, does that index exist?
    index_conf = getMergedConf('indexes')
    if not indexName in index_conf:
      logger.info("There is no index %s configured." % indexName)
      return
              
    skip_confirmation = skipConfirm(args)
    if not skip_confirmation:
      logger.info("This action will rebuild metadata; it cannot be undone.")
      confirmed = prompt_user()
      
    if confirmed:
      # make a copy of the dict so we can add the correct endpoint path
      myArgs = args.copy()
      endpointPath = "/data/indexes/%s/rebuild-metadata" % indexName
      myArgs["path"] = endpointPath
      
      # done with this now, remove if exists. restCall doesn't like it
      if "force" in args:
        del myArgs["force"]
          
      # call the endpoint
      # note splunkd validates index name but doesn't propagate any errors back yet
      restCall(myArgs, fromCLI)
          
      logger.notice("Rebuilding metadata request submitted for execution.")
          
    else:
      logger.notice("Rebuilding metadata cancelled")
          
  return True
                                                                                                                    
def rebuildBucketManifests(args, fromCLI):
  """
  Rebuild the bucket manifests for the specified index via rest
  """
  
  paramsReq = ("index",)
  paramsOpt = ("force",)
  validateArgs(paramsReq, paramsOpt, args, exceptionOnUnknownArgs = False)
  
  indexName = args.pop("index")
  logger.notice("Rebuilding bucket manifests for index '%s'." % indexName)
  
  # set this here so force (if provided) can perform requested action
  confirmed = True
  
  if fromCLI:
    # first, does that index exist?
    index_conf = getMergedConf('indexes')
    if not indexName in index_conf:
      logger.info("There is no index %s configured." % indexName)
      return
              
    skip_confirmation = skipConfirm(args)
    if not skip_confirmation:
      logger.info("This action will rebuild bucket manifests; it cannot be undone.")
      confirmed = prompt_user()
      
    if confirmed:
      # make a copy of the dict so we can add the correct endpoint path
      myArgs = args.copy()
      # this is not a typo, the endpoint doesn't have an 's' at the end
      endpointPath = "/data/indexes/%s/rebuild-bucket-manifest" % indexName
      myArgs["path"] = endpointPath
      
      # done with this now, remove if exists. restCall doesn't like it
      if "force" in args:
        del myArgs["force"]
          
      # call the endpoint
      # note splunkd validates index name but doesn't propagate any errors back yet
      restCall(myArgs, fromCLI)
          
      logger.notice("Rebuilding bucket manifests request submitted for execution.")
          
    else:
      logger.notice("Rebuilding bucket manifests cancelled")
          
  return True
        


def rebuildMetadataAndManifests(args, fromCLI):
  """
  Rebuild the *.data files and manifests for the specified index via rest
  """

  paramsReq = ("index",)
  paramsOpt = ("force",)
  validateArgs(paramsReq, paramsOpt, args, exceptionOnUnknownArgs = False)
  
  indexName = args.pop("index")
  logger.notice("Rebuilding metadata and manifests for index '%s'." % indexName)
  
  # set this here so force (if provided) can perform requested action
  confirmed = True
  
  if fromCLI:
    # first, does that index exist?
    index_conf = getMergedConf('indexes')
    if not indexName in index_conf:
      logger.info("There is no index %s configured." % indexName)
      return
              
    skip_confirmation = skipConfirm(args)
    if not skip_confirmation:
      logger.info("This action will rebuild metadata and manifests; it cannot be undone.")
      confirmed = prompt_user()
      
    if confirmed:
      # make a copy of the dict so we can add the correct endpoint path
      myArgs = args.copy()
      endpointPath = "/data/indexes/%s/rebuild-metadata-and-manifests" % indexName
      myArgs["path"] = endpointPath

      # done with this now, remove if exists. restCall doesn't like it
      if "force" in args: 
        del myArgs["force"]
        
      # call the endpoint
      # note splunkd validates index name but doesn't propagate any errors back yet
      restCall(myArgs, fromCLI)
      
      logger.notice("Rebuilding metadata and manifests request submitted for execution.")
        
    else:
      logger.notice("Rebuilding metadata and manifests cancelled")
        
  return True

def getSplunkdServiceName():
  if "SPLUNK_SERVER_NAME" in os.environ:
    return os.environ["SPLUNK_SERVER_NAME"] + build_info.SVC_SUFFIX
  return build_info.SVC_SPLUNKD

def getSplunkwebServiceName():
  if "SPLUNK_WEB_NAME" in os.environ:
    return os.environ["SPLUNK_WEB_NAME"] + build_info.SVC_SUFFIX
  return build_info.SVC_SPLUNKWEB

