#   Version 3.0
#!/usr/bin/env python



import os, time, stat, re, sys
from findutils import *
import interactiveutils

all_files = {}
g_ignored_paths = []
g_log_files = {}

MAX_BADFILES_PER_DIR = 100
PRINT_STATUS_SECS = 5
BIG_DIR_FILECOUNT = 10000

g_last_print_time = time.time()
g_dir_count = 0
#g_quiet = False
g_skip_big = False
g_config = {}
g_day_size_pair = g_bad_dir = g_bad_ext = g_bad_pat = []

def findLogs(searchpaths):
    for path in searchpaths:
        os.path.walk(path, processPath, None)

def ignoreFilename(filename):
    for path in g_ignored_paths:
        if filename.startswith(path):
            #print "IGNOREFILENAME:", filename
            return True
    return False

def processPath (unused, dirname, files):
    global g_log_files, g_last_print_time, g_dir_count, g_quiet, g_skip_big

    g_dir_count += 1
    
    removedFilenames = []
    for filename in files:
        if re.search(g_bad_pat, filename) != None:
            #print "REMOVED ENDING:", filename
            removedFilenames.append(filename)
        elif filename.lower() in g_bad_dir:
            #print "REMOVED BAD DIRECTORY:", filename
            removedFilenames.append(filename)
        else:
            endsplit = filename.split("/")[-1].split(".")
            if len(endsplit) > 1:
                extension = endsplit[-1]
                if extension in g_bad_ext:
                    #print "REMOVED BAD EXTENSION:", dirname, filename                
                    removedFilenames.append(filename)
            
    for filename in removedFilenames:
        files.remove(filename)

    filecount = len(files)
    isBigDir = filecount > BIG_DIR_FILECOUNT

    if isBigDir:
        if g_skip_big:
            return
        if not g_quiet:
            print "Directory", dirname, "has", filecount, "file(s).\n\tSkip it (Yes/No/Always/Never)? ", # TK ESD 3/11/08
            answer = raw_input().strip()
            if len(answer) > 0:
                answer = answer.lower()
                if answer == "always":
                    g_quiet = True
                    g_skip_big = True
                    return
                elif answer == "never":
                    g_quiet = True
                    g_skip_big = False
                elif answer == "yes":
                    return

##     for filename in files:
##         if filename.endswith("tar"):
##             print "STILL GOOD!", filename

        
    foundGood = False
    count = 0
    fullpaths = []
    now = time.time()

    # Traversal function for directories
    for filename in files:
        #print count,"\t", filename
        try:
            now = time.time()
            if (now - g_last_print_time ) > PRINT_STATUS_SECS:
                print "Processed " + str(g_dir_count)  + " directory/ies (Currently in '" + dirname + "')" # TK ESD 3/11/08
                g_last_print_time = now

            fullpath = os.path.join(dirname, filename)
            if not ignoreFilename(fullpath):
                t = os.stat(fullpath)
                size = t.st_size
                modtime = t.st_mtime
                isfifo = stat.S_ISFIFO(t.st_mode)
                # IF BIG ENOUGH AND RECENT ENOUGH AND NOT A PIPEDFILE AND LOOKS LIKE TEXT
                if not isfifo :
                    for days,minSizeK in g_day_size_pair:
                        timeCutoff = now - (days * 24*60*60)
                        if size*1024 > minSizeK and modtime > timeCutoff and (isCompressed(g_config, fullpath) or isText(fullpath)):
                            g_log_files[fullpath] = (modtime, size, "unknown")
                            foundGood = True
                            fullpaths.append(fullpath)
                            break
            if not foundGood:
                count += 1
            if count > MAX_BADFILES_PER_DIR:
                if not g_quiet:
                    print "\tSkipping unpromising directory:", dirname  # TK ESD 3/11/08
                break
        except KeyboardInterrupt, e:
            raise KeyboardInterrupt, e
        except Exception, e:
            if not g_quiet:
                print "Problem processing file:", e, "\n\tSkipping:", filename  # TK ESD 3/11/08
    ftypes = getFileTypes(fullpaths)
    for fullpath, sourcetype in ftypes.items():
        if fullpath in g_log_files:
            modtime, size, dummy = g_log_files[fullpath]
            g_log_files[fullpath] = (modtime, size, sourcetype)

REGION_SIZE = 100 # BAD IT FASTER AND LESS ACCURATE FROM VALUE USED IN FILECLASSIFIER (1000)
NORMAL_TEXT_MAX_LEN = 400 
LINE_MAX = 2048

# copied from fileclassifier.py
def isText(filename):
    try:
        f = open(filename, 'rb')
        goodLines = 0
        badLines = 0
        for i in range(0, REGION_SIZE):
            line = f.readline()
            if len(line) == 0:
                break
            if len(line) > LINE_MAX:
                badLines += 1
            elif not enoughText(line):
                badLines += 1
            elif len(line) < NORMAL_TEXT_MAX_LEN:
                goodLines += 1
        f.close()
        textp = (goodLines > 2 * badLines)
        # print filename, "ISTEXT? ", textp
        return textp
    except KeyboardInterrupt, e:
        raise KeyboardInterrupt, e
    except: # Exception, e:
        #print 'Error reading file: ' + filename + '. ' + str(e)
        return False

def enoughText(line):
    totalcount = len(line)
    if totalcount == 0:
        return True
    badcount = len([1 for ch in line if ord(ch) < 32 and not ch.isspace()])
    return badcount < 10 



# returns terms that occur between min and max times.
def sortByTime(files):
    filesAndTimes = files.items()
    filesAndTimes.sort( lambda x, y: y[1][0] - x[1][0] ) 
    return [ft[0] for ft in filesAndTimes]

def getSortedLogs():
    "Sorts files from most to least recent. Puts all files that have 'log' in their name ahead of all those that do not."
    ##sortedFiles = sortByTime(g_log_files)
    sortedFiles = list(g_log_files.keys())
    sortedFiles.sort()
    best = []
    medium = []
    worst = []
    zipped = []
    for fname in sortedFiles:
        modtime, size, sourcetype = g_log_files[fname]
        if sourcetype.startswith("preprocess"):
            zipped.append(fname)
        elif sourcetype in ['too_small', 'unknown']:
            worst.append(fname)
        elif "-U" in sourcetype or sourcetype.startswith("unknown-"):
            medium.append(fname)
        else:
            best.append(fname)
    result = best + medium + worst + zipped
    return result


def startSplunk():
    if sys.platform.startswith("win"):
        exit("Error: Windows platform not supported for this deprecated command.  Use the 'crawl' search operator.")
    
    import commands
    output = commands.getstatusoutput("splunk status|grep splunkd|grep not")[1]
    if len(output.strip()) > 0:
        print "Splunkd not started.  Starting..."  # TK ESD 4/25/08
        output = commands.getstatusoutput("splunk start|grep splunkd")[1]
        if "FAIL" in output:
            return False
    return True
    
def addFile(filename, auth):
    # There's no additional cost in tailing files vs. batch indexing them,
    # with the exception that compressed (e.g., tar, gz, ..) files are not handled by tailing.
    if isCompressed(g_config, filename):
        cmd = "splunk spool \"" + filename + "\" -auth " + auth
    else:
        cmd = "splunk add tail \"" + filename + "\" -auth " + auth
    ret = os.system(cmd)
    if ret != 0:
        print "Problem encountered while adding file '" + filename + "'.  Error code returned = " + str(ret) + "."  # TK ESD 3/11/08

if __name__ == '__main__':

    #global g_quiet, g_ignored_paths, g_config
    args = [v for v in sys.argv if len(v) > 0]

    # if called with "logs" as in old way of calling, remove that arg
    if len(args) > 1 and args[1].strip().lower() == "logs":
        args.pop(1)
    
    argcount = len(args)

    
    if (argcount < 2) or (len(args[1]) == 0):
        print # TK ESD 4/25/08
        print 'Splunk find logs -- Finds potential log files on your system.  '
        print        
        print '\tSet which directories and files to ignore'
        print '\tand file size and modification date restrictions in findlogs.conf'
        print        
        print 'Usage:'
        print
        print '\tfind logs "searchpath1;searchpath2;..." '
        print
        print 'Example:'
        print
        print '\tTo find log files under the root directory ("/"), use:'
        print
        print '\t\tfind logs "/" '
        print
    else:
        try:
            g_quiet = True
            if args[argcount-1].lower() == "verbose":
                g_quiet = False
                argcount -= 1

            searchpaths = (args[1]).split(";")
##             if argcount > 2:
##                 g_ignored_paths = (args[2]).split(";")

            splunkhome = os.getenv("SPLUNK_HOME")
            if splunkhome != None:
                g_ignored_paths.append(splunkhome)

            g_config = loadConfig(CONFIG_FILE)
            g_bad_dir = set(g_config['BAD_DIRECTORIES'])
            g_bad_ext = set(g_config['BAD_EXTENSIONS'])
            pat = "(?i)^" + listToRegex([pattern.replace(".", "\.").replace("*", ".*") for pattern in g_config['BAD_FILE_MATCHES']]) + "$"
            g_bad_pat = re.compile(pat)

            g_day_size_pair = getDaysSizeKPairs(g_config)


            findLogs(searchpaths)
            if len(g_log_files) == 0:
                print "Found no potential log files." # TK ESD 3/11/08
            else:     
                sortedFiles = getSortedLogs()
                print "Processed " + str(g_dir_count)  + " directory/ies " # TK ESD 3/11/08
                print
                print "POTENTIAL LOG FILES"
                print "-"*80
                print "\t","TIME".rjust(20), "SIZE (K)".rjust(20), "SOURCETYPE".rjust(20), "\t", "NAME"
                print "-"*80
                for name in sortedFiles:
                    modtime, size, sourcetype = g_log_files[name]
                    if sourcetype == None or sourcetype == "too_small":
                        sourcetype = "unknown"
                    if size < 1024:
                        size = 1
                    else:
                        size /= 1024
                    print "\t", time.ctime(modtime).rjust(20), str(size).rjust(20), sourcetype.rjust(20), "\t", name

                if interactiveutils.askYesNoQuestion("Collapse files into common directories?"): # TK ESD 4/25/08
                    sortedFiles = recursivelyFindCommonDirectories(g_config, sortedFiles, int(g_config['COLLAPSE_THRESHOLD'][0]))
                    print
                    print "Collapsed files:"
                    print "-"*80
                    for fname in sortedFiles:
                        print "\t", fname
                    
                ALL = "all"; SOME = "some"; NOPE = "none"; YES = "yes"; NO = "no"; ABORT = "abort"
                answer = interactiveutils.askMultipleChoiceQuestion("Index found files into Splunk?", [ALL, SOME, NOPE], NOPE) #TK ESD 3/11/08
                auth = "admin:changeme"
                if answer != NOPE:
                    success = startSplunk()
                    if not success:
                        print "Unable to start splunkd.  Exiting..."  # TK ESD 3/11/08
                        sys.exit()
                    username = interactiveutils.promptWithDefault("splunk username", "admin")
                    password = interactiveutils.promptPassWithDefault("splunk password", "changeme")
                    auth = username + ":" + password
                if answer == ALL:
                    for fname in sortedFiles:
                        addFile(fname, auth)
                elif answer == SOME:
                    for fname in sortedFiles:
                        fileanswer = interactiveutils.askMultipleChoiceQuestion("Index " + str(fname) + " into Splunk?", [YES, NO, ABORT], NO) #TK ESD 3/11/08
                        if fileanswer == YES:
                            addFile(fname, auth)
                        elif fileanswer == ABORT:
                            break
                    
        except KeyboardInterrupt, e:
            print "\nExiting...\n"
    
