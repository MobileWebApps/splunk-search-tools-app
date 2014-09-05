#   Version 3.0
#!/usr/bin/env python


import sys
if sys.platform.startswith("win"):
     exit("Error: Windows platform not supported for this deprecated command.  Use the 'crawl' search operator.")

import re,time,commands
import interactiveutils,dcutils
from threading import Thread
import thread
from findutils import *

try:
     import pexpect #pylint: disable-msg=F0401
except:
     exit("Error: pexcept module required.  Please install from http://www.noah.org/wiki/Pexpect#Download_and_Installation.")

MAC_OS     = "darwin"
SOLARIS_OS = "sunos"
LINUX_OS   = "linux"
UNKNOWN_OS = "unknown"
KNOWN_OS = set([MAC_OS, SOLARIS_OS, LINUX_OS])

BYTES_PER_BLOCK = 512
LINE = "-"*80


g_quiet = False
g_debug = False
g_lock=thread.allocate_lock()


# executes commandline and returns a list of lines output
def execCmd(cmd, password=None):

     if g_debug:
          print "DEBUG:\t", cmd
#     g_lock.acquire()     
     if password != None:
          output = execCmdWithPassword(cmd, password)
     else:
          output = commands.getstatusoutput(cmd)[1]
#    g_lock.release()
          
     if output == None:
          return None
     return re.split( "[\r\n]+", output)



# This is the prompt we get if SSH does not have the remote host's public key stored in the cache.
SSH_NEWKEY = '(?i)are you sure you want to continue connecting'
PASSWORD =  "(?i)password:"

def execCmdWithPassword(command, password):
     try:
          #sshcmd = 'ssh -l %s %s "%s"'%(user, host, command)
          #print command
          child = pexpect.spawn(command)    
          ret = child.expect([pexpect.TIMEOUT, SSH_NEWKEY, PASSWORD], 10)
          if ret == 0:
               if g_debug:                              
                    print "Timed out logging in."
               return None
          if ret == 1:
               child.sendline("yes")
               i = child.expect([pexpect.TIMEOUT, PASSWORD], 10)
               if i == 0: # Timeout
                    if g_debug:               
                         print "Timed out logging in."
                    return None
          child.sendline(password)
          ret = child.expect([pexpect.TIMEOUT, pexpect.EOF], -1) # wait a while
          if ret == 0:
               if g_debug:               
                    print 'Command timed out.'
               return None
          return child.before
     except KeyboardInterrupt, e:
          raise e
     except Exception, e:
          if g_debug:
               print "Problem executing command:", command[0:50],"...\n\tException:", e
          return ""
   


def getFilesCommand(config, startingDirs, daysSizeKPairs, hostOS):

     badfiletyperegex = listToRegex(config['BAD_FILE_TYPES'])
     goodtypesregex   = listToRegex(config['GOOD_FILE_TYPES'])
     startingdirs     = "'" + "' '".join(startingDirs) + "'"
     
     findspec  = " find "
     if True or hostOS == SOLARIS_OS:
          findspec += startingdirs + " -xdev -type d "
          first = True
          for baddir in config['BAD_DIRECTORIES']:
               if not first:
                    findspec += " -o "
               first = False
               findspec += " -name '" + baddir + "' -prune "

          for maxDays, minSizeK in daysSizeKPairs:
                    findspec += " -o -mtime -" + str(maxDays) + " -type f -size +" + str(minSizeK*2) + "  -print "
          filters   = "|sed 's/ /\\ /'|xargs file -- |egrep -i '" + goodtypesregex + "'|egrep -vi ' " + badfiletyperegex + " ' |cut -d ':' -f 1"
          cmd = findspec + filters
     else:
          if hostOS == MAC_OS:
               findspec += " -E "
               baddirfindregex  = ".*/(" + "|".join(config['BAD_DIRECTORIES']) + ")/.*"
          else:
               baddirfindregex  = ".*/\(" + "\|".join(config['BAD_DIRECTORIES']) + "\)/.*"
          
          findspec += startingdirs + " -xdev \("
          findspec += " -iregex '" + baddirfindregex + "' -prune "
          for maxDays, minSizeK in daysSizeKPairs:
              findspec += " -o -mtime -" + str(maxDays) + " -type f -size +" + str(minSizeK*2) + "  -print0 "
          findspec += " \)"
               
          filters   = "|xargs -0 file -- |egrep -i '" + goodtypesregex + "'|egrep -vi ' " + badfiletyperegex + " ' |cut -d ':' -f 1"
          cmd = findspec + filters
     return cmd

def getSSHCommand(user, host, cmd, hostOS):
##     if not g_quiet:
##          print "Connecting to", host, "as", user,"..."
    cmd = cmd.replace("\"", "\\\"")
    cmd = cmd.replace("'", "\'")
##     if hostOS != MAC_OS: 
##          cmd = cmd.replace("(", "\(")
##          cmd = cmd.replace(")", "\)")
    cmd = cmd.replace("$", "\$")
    return "ssh " + user + "@" + host + " \"" + cmd + " \""
        
def getOS(user, password, host):
     cmd = "uname -a"
     cmd = getSSHCommand(user, host, cmd, False)
     output = execCmd(cmd, password)
     if output == None:
          return None
     osval = UNKNOWN_OS
     output = [v for v in output if len(v.strip()) > 0] # remove blank lines
     if len(output) > 0 and len(output[0]) > 0 and output[0][0].isalpha():
          hostOS = output[-1].split()[0].lower()  # get last (successful) response to the password.  Get first word (OS)
          if hostOS in KNOWN_OS:
               osval =  hostOS
          elif g_debug:
               print "DEBUG:\t Unknown OS:", hostOS
##      if not g_quiet:
##          print host + "'s OS is '" +  osval + "'"               
     return osval

MAX_LINE = 900  # break ssh commands up from being too long


def getOutputDirectory(host):
     return config['TMP_DATA_DIRECTORY'][0].strip() + "/" + host


def copyFiles(user, host, password, files):
     if len(files) == 0:
          return
     outdir = getOutputDirectory(host)
     execCmd("mkdir -p " + outdir)
     filesToProcess = list(files)
     filelist = ""
     count = 0
     while len(filesToProcess) > 0:
          count+=1
          if count % 100 == 0:
               if not g_quiet:
                    print "\tCopied", count, "out of", len(files),"from", host,"..."
          file = filesToProcess.pop()
          filelist += " '" + file + "' "
          if len(filelist) > MAX_LINE or len(filesToProcess) == 0:
               cmd = "ssh " + user + "@" + host + " \"tar cf - " + filelist + "\" -- | tar xf - -C '" + outdir + "'"
               if g_debug:
                    print "Executing:", cmd
               execCmd(cmd, password)
               filelist = ""

     
def copyFileHeads(user, host, password, files):
     if len(files) == 0:
          return
     outdir = config['TMP_DATA_DIRECTORY'][0].strip() + "/" + host
     execCmd("mkdir -p " + outdir)
     filesToProcess = list(files)
     while len(filesToProcess) > 0:
          file = filesToProcess.pop()
          sep = file.rfind('/')
          dir = file[:sep]
          thisoutdir = outdir + dir
          mkdircmd = "mkdir -p '" + thisoutdir + "'"
          execCmd(mkdircmd)
          # sh -c needed because execmd doesn't break ssh command at ">"
          cmd = "sh -c 'ssh " + user + "@" + host + " \"tail -n " + str(MAX_HEAD) + " " + makeSafeFile(file) + "\" -- > " + makeSafeFile(outdir + file) + "'"
          if g_debug:
               print "Executing:", cmd
          execCmd(cmd, password)
          
def getFileSizeInfo(user, host, password, files):
     info = {}
     if len(files) == 0:
          return
     filesToProcess = list(files)
     filelist = ""
     while len(filesToProcess) > 0:
          file = filesToProcess.pop()
          filelist += " '" + file + "' "
          if len(filelist) > MAX_LINE or len(filesToProcess) == 0:
               cmd = "ssh " + user + "@" + host + " \"ls -s " + filelist + "\""
               if g_debug:               
                    print "Executing:", cmd
               outlines = execCmd(cmd, password)
               for line in outlines:
                    sep = line.find(" /")
                    if sep >= 0:
                         size = int(line[:sep])
                         file = line[sep+1:]
                         info[file] = size
                         
               filelist = ""
     return info

# /////////////////////////////


# /////////////////////////////

MAX_HEAD = 10000 # 10k lines
MAX_COPY_BLOCKS = 500 # 250K
def smartCopyFiles(user, host, password, info):
     if info == None:
          if not g_quiet:
               print "Unable to get file details for host", host
          return 
     smallfiles = []
     largefiles = []
     bigpackedfiles = []

     packedpattern = re.compile("(?i)\." + listToRegex(config['PACKED_EXTENSIONS']) + "$")        
     for file, blocks in info.items():
          if blocks >= MAX_COPY_BLOCKS:
               if re.search(packedpattern, file) != None:
                    bigpackedfiles.append(file)
               else:
                    largefiles.append(file)
          else:
               smallfiles.append(file)
     #print "SMALL FILES:", smallfiles
     #print "BIG FILES:", largefiles
     copyFiles(user, host, password, smallfiles)
     copyFileHeads(user, host, password, largefiles)
     count = len(smallfiles) + len(largefiles)
     print LINE
     print "Copied", count, "files from", host + "."
     bigcount = len(bigpackedfiles)
     if bigcount > 0:
          print "Ignoring",len(bigpackedfiles), "large compressed files."
          if not g_quiet:
               print "Ignored large compressed files:"
               print "\t" + "\n\t".join(bigpackedfiles)

def getHostsViaNMap(config):
     maskbits = getMaskBits(config)
     cmd = "nmap -sP $HOSTNAME/" + str(maskbits)
     if not g_quiet:             
          print "Executing: ", cmd
     hosts = execCmd(cmd + "|grep Host|cut -d ' ' -f 2 ")
     hosts = [host for host in hosts if not("failed" in host.lower() or "warning" in host.lower() or "error" in host.lower() or "quit" in host.lower())]
     return hosts
          
# use unix commands to find all hosts
def getHostsViaHosts():
    try:
        hosts = []
        domain = execCmd("cat /etc/resolv.conf | egrep 'search|domain'|awk '{print $2}'")
        cmd = "host -l " + domain[0]
        if not g_quiet:                  
             print "Executing: ", cmd        
        hosts = execCmd(cmd + "|egrep -v '^#' | awk '{print $1}' | cut -d . -f 1 | sort | uniq")
    except Exception, e:
        print "Unable to get remote hosts names automatically:", e
    return hosts

# returns the number of bits used in the mask returned by ifconfig.  uses most restrictive mask, if multiple
def getMaskBits(config):
     lines = execCmd("/sbin/ifconfig -a|egrep -o 'Mask:([^ ]+)'|egrep -o '[0-9.]+'")
     maxcount = -1
     for line in lines:
          count = len(re.findall("255", line))
          if count > maxcount:
               maxcount = count
     if maxcount > 0:
          maxcount *= 8  # 8bits in a byte
     else:
          maxcount = int(config['DEFAULT_MASK_BITS'][0])
          print "Unable to find network Mask.  Using default."
     return maxcount

# ask user to supply machins        
def manualListHosts():
    hosts = []
    if interactiveutils.askYesNoQuestion("Would you like to manually enter additional remote host names?", False):
        interactiveutils.addListItems("Please enter the names of remote hosts to search for log files.", "remote-host", hosts, isValidHost)
    return hosts

# validate host 
def isValidHost(hostname):
    lines = execCmd("ping -c1 " + hostname)
    for line in lines:
        if "packets" in line:
            return True
    return False
     

def getHosts(config):
     hosts = []
     # get patterns and replace friendly "*" with regex-correct pattern ".*"
     patterns = [pattern.replace("*", ".*") for pattern in config['IGNORED_HOSTS']]
     regex = listToRegex(patterns)
     while True:
          needsApprove = False
          operation = interactiveutils.askMultipleChoiceQuestion("How should I get the names of hosts to search? (default=nmap)", ['nmap', 'hosts', 'manually', 'quit'], 'nmap')
          if operation == 'nmap':
               hosts = getHostsViaNMap(config)
               needsApprove = True
          elif operation == 'hosts':
               hosts = getHostsViaHosts()
               needsApprove = True
          elif operation == 'manually':
               interactiveutils.addListItems("Please enter the names of remote hosts to search for log files.", "remote-host", hosts, isValidHost)
          elif operation == 'quit':
               break
          # didn't get any hosts
          if hosts == None or len(hosts) == 0:
               print "Unable to get hosts with that method.  Please try another method."
          else: # got some hosts
               hosts = [host for host in hosts if re.search(regex, host.lower()) == None]
               hosts.sort()
               if needsApprove:
                    hosts = interactiveutils.validateElements("hosts", hosts)
               if len(hosts) > 0:
                    break
     return hosts

def getFiles(config, user, password, host, startingDirs, daysSizeKPairs, collapseThreshold):
     hostOS = getOS(user, password, host)
     if hostOS == None:
          if not g_quiet:          
               print "Unable to log into host " + host + ".  Skipping..."
          return []
     cmd = getFilesCommand(config, startingDirs, daysSizeKPairs, hostOS)
     cmd = getSSHCommand(user, host, cmd, hostOS)
     #print cmd
     files = execCmd(cmd, password)
     if files == None:
          print "Unable to get files from host " + host + ".  Skipping..."
          return []
     goodfiles = filterFiles(config, files)
     #goodfiles = findCommonDirectories(config, goodfiles, collapseThreshold)
     #sortedFiles = sortFiles(config, goodfiles)
     return goodfiles


     
def filterFiles(config, files):
     import re
     patterns = [pattern.replace(".", "\.").replace("*", ".*") for pattern in config['BAD_FILE_MATCHES']]
     p1  = "(?i)\." + listToRegex(config['BAD_EXTENSIONS']) + "$"    # *.gifONS']) + "$"    # *.gif
     p2  = "(?i)\." + listToRegex(config['BAD_EXTENSIONS']) + "\."   # *.gif.2
     p3  = "(?i)"   + listToRegex(patterns) + "$"    # *readme
     pats = [p1, p2, p3]
     goodfiles = []
     warnings = 0
     for filename in files:
          #print filename
          if len(filename) == 0:
               continue
          if filename[-1] == ':':
               filename = filename[0:len(filename)-1]
          last = filename[-1]
          # if it's a file (not an error)
          if filename.startswith("/"):
               for pat in pats:
                    if re.search(pat, filename) != None:
                         #print "BADFILENAME:", filename
                         break
               else:
                    goodfiles.append(filename)
          elif len(filename.strip()) > 0 and not "permission" in filename.lower() and not "stale" in filename.lower():
               print "Warning:", filename
               warnings += 1
     return goodfiles


class Crawler(Thread):
   def __init__ (self,config, user, password, host, dir, daysSizeKPairs, collapseThreshold, copyfiles):
      Thread.__init__(self)
      self.files = []
      self.config = config
      self.user = user
      self.password = password
      self.host = host
      self.dir = dir
      self.daysSizeKPairs = daysSizeKPairs
      self.collapseThreshold = collapseThreshold
      self.copyfiles = copyfiles
      self.sizeinfo = {}
      self.sourcetypes = {}
   def run(self):
        try:
             self.files = getFiles(self.config, self.user, self.password, self.host, self.dir, self.daysSizeKPairs, self.collapseThreshold)
             if len(self.files) > 0:
                  self.sizeinfo = getFileSizeInfo(self.user, self.host, self.password, self.files)        
                  if self.copyfiles:
                       smartCopyFiles(self.user, self.host, self.password, self.sizeinfo)
                       self.sourcetypes = getFileTypes(self.files, getOutputDirectory(self.host))
        except Exception, e:
             print "\nError with host " + host + ". Skipping...\n\tException: ", e, "\n"
             import traceback
             traceback.print_exc()

                  
   def getFiles(self):
        return self.files
   def getHost(self):
        return self.host
   def getSizeInfo(self):
        return self.sizeinfo
   def getSourceTypeInfo(self):
        return self.sourcetypes

# doesn't display password
def getPassword(text):
     import getpass
     text += " >"
     text = text.rjust(60)        
     return getpass.getpass(text + " ")

def printLine(size, type, file):
   size = str(size).rjust(20)
   type = str(type).rjust(30)
   print "\t" + size + "  " + type + "  " + file

def printSubtotalLine(type, size):
   type = str(type).rjust(20)
   print "\t" + type + "  " + str(size)


def printInfo(sizeinfo, sourcetypes, host):
     if sizeinfo == None:
          print "No sizeinfo for host", host
          return
     print "\n" + str(len(sizeinfo)) + " files found on", host, "..."
     print LINE
     printLine("SIZE (K)", "SOURCETYPE", "FILE")
     print LINE
     sortednames = sizeinfo.keys()
     sortednames.sort()
     total = 0
     totalByType = {}
     for file in sortednames:
          size = sizeinfo[file] * BYTES_PER_BLOCK
          sourcetype = sourcetypes.get(file, "Unknown")
          dcutils.incCount(totalByType, sourcetype, size)
          total += size
          printLine(size, sourcetype, file)
     print LINE 
     printLine(total, "TOTAL SIZE (K)", "")     
     sortedTypes = dcutils.getBestTerms(totalByType)
     print "\n\tSource Type Subtotals"
     print "\t" + LINE 
     printSubtotalLine("SOURCE-TYPE", "SIZE (K)")
     print "\t" + LINE
     for stype in sortedTypes:
          size = totalByType[stype]
          printSubtotalLine(stype, size)

if __name__ == '__main__':
    try:
         import os
         os.putenv("DISPLAY", "")
         config = loadConfig(CONFIG_FILE)
         if config == None:
              print "Unable to load configuration from", "findlogs.conf"
              exit
         collapseThreshold = 3
         daysSizeKPairs = getDaysSizeKPairs(config)  #[(7, 0), (30, 1000)] # find files <7days&>1k or <30days&>1m
    
         aCount = len(sys.argv)
    
         if aCount == 2:
              last = sys.argv[-1].lower()
              if last.startswith("debug"):
                   g_debug = True
              elif last.startswith("quiet"):
                   g_quiet = True
              else:
                   print "\n\tUsage:", sys.argv[0], "[debug|quiet]\n"
                   sys.exit()
              
         user = interactiveutils.promptWithDefault("username", "root")
         dir = interactiveutils.promptWithDefault("starting directory", "/")
         manyhosts = interactiveutils.askMultipleChoiceQuestion("Run on more than one host? (default=no)", ['no', 'yes'], 'no')
         copyfiles = 'yes' == interactiveutils.askMultipleChoiceQuestion("Do you want to retrieve the files found for further inspection?", ['yes', 'no'], 'yes')
         
         if manyhosts == 'yes':
               hosts = getHosts(config)
               password = None
               if interactiveutils.askYesNoQuestion("Do you want to automatically use a common password for all hosts?", False):
                    password = getPassword("Enter remote password")
    
    
               crawlerThreads = []
               for host in hosts:
                    crawler = Crawler(config, user, password, host, [dir], daysSizeKPairs, collapseThreshold, copyfiles)
                    crawlerThreads.append(crawler)
                    try:
                         crawler.start()
                    except Exception, e:
                         print "\nError. Skipping", host, "...", e, "\n"
    
               noresultshosts = []
               for crawler in crawlerThreads:
                    crawler.join()
                    files = crawler.getFiles()
                    sizeinfo = crawler.getSizeInfo()
                    sourcetypes = crawler.getSourceTypeInfo()
                    host = crawler.getHost()
                    if len(files) == 0:
                         noresultshosts.append(host)
                    else:
                         printInfo(sizeinfo, sourcetypes, host)

               if len(noresultshosts) > 0:
                    print "No results from:", noresultshosts
         else:
              host = interactiveutils.prompt("host", False)
              path = getOutputDirectory(host)
              password = getPassword("Enter password for " + user + "@" + host)              
              files = getFiles(config, user, password, host, [dir], daysSizeKPairs, collapseThreshold)
              sizeinfo = getFileSizeInfo(user, host, password, files)
              sourcetypes = {}
              if copyfiles:
                   smartCopyFiles(user, host, password, sizeinfo)
                   sourcetypes = getFileTypes(files, getOutputDirectory(host))                   
              printInfo(sizeinfo, sourcetypes, host)
        
    except KeyboardInterrupt, e:
         print "\nExiting...\n"
##     except Exception, e:
##          print 'Error:', e
