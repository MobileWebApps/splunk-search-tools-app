import os
import subprocess
import sys
import platform
import shutil
import tarfile
import stat
import logging
import splunk.clilib.cli_common
import datetime
import time # two time modules, zzz
import optparse
import fnmatch
import re
import glob
import socket
import traceback
import StringIO
import splunk.clilib.bundle_paths
import tempfile

SPLUNK_HOME   = os.environ['SPLUNK_HOME']
RESULTS_LOC   = os.path.join(SPLUNK_HOME, 'var', 'run', 'splunk', 'diag-temp')
MSINFO_FILE   = 'msinfo-sum.txt'
SYSINFO_FILE  = 'systeminfo.txt'
COMPOSITE_XML = os.path.join(SPLUNK_HOME, 'var', 'run', 'splunk', 'composite.xml')

KNOWN_COMPONENTS = ("index_files", 
                    "index_listing", 
                    "dispatch", 
                    "etc", 
                    "log", 
                    "pool")

system_info = None # systeminfo.txt file obj; if you want to use reporting
                   # functions externally, set this as desired.

# SPL-34231, horrid (microsoft) hack to support longer filenames --
# normally windows rejects 260+ char paths, unless unicode and
# containing this magic cookie
windows_magic_filepath_cookie = u"\\\\?\\"
def bless_long_path(path):
    if os.name == "nt":
        return windows_magic_filepath_cookie + path
    return path

##################
# various cruft around naming the diag file.
#
def get_diag_date_str():
    return datetime.date.today().isoformat()

def get_splunkinstance_name():
    # Octavio says the hostname is preferred to machine-user, and that
    # multiple-splunks-per-host is now rare, so just use hostname
    return socket.gethostname()

def get_results_dir():
    results_path = os.path.join(RESULTS_LOC, get_diag_name())
    return bless_long_path(results_path)

#def get_diag_name():  # impelmented via generator
def _diag_name_generator():
    # hack to create 'static' value
    date_str = get_diag_date_str()
    servername = get_splunkinstance_name()
    diag_name = "diag-%s-%s" % (servername, date_str)
    logging.info('Selected diag name of: ' + diag_name)
    while True:
        yield diag_name
get_diag_name = _diag_name_generator().next

def get_tar_name():
     return(os.path.join(SPLUNK_HOME, get_diag_name() + ".tar.gz"))

##################
# main utility functions to gather data
#
def sytemUsername():
    if os.name == 'posix':
        import pwd
        # get the name for the UID for the current process
        username = pwd.getpwuid(os.getuid())[0]
    elif os.name == 'nt':
        # thanks internets -- http://timgolden.me.uk/python/win32_how_do_i/get-the-owner-of-a-file.html`
        #pylint: disable=F0401
        import win32api
        import win32con
        username = win32api.GetUserNameEx(win32con.NameSamCompatible)
    else:
        username = 'unknown for platform:' + os.name
    system_info.write('diag launched by: ' + username)

def splunkVersion():
    """ Use splunk version to figure the version"""

    system_info.write('\n\n********** Splunk Version **********\n\n')
    sver = os.popen('splunk version')
    system_info.write(sver.read())


# this uses python's uname function to get info in a cross-platform way.
def systemUname():
    """ Python uname output """ 

    system_info.write('\n\n********** Uname **********\n\n')
    suname = platform.uname()
    system_info.write(str(suname))
    #SPL-18413
    system_info.write("\n")
    system_info.write('\n\n********** splunkd binary format **********\n\n')
    splunkdpath = os.path.join(SPLUNK_HOME, 'bin', 'splunkd') 
    if suname[0] == 'Windows':
        splunkdpath += ".exe"
    arch = str(platform.architecture(splunkdpath)) 
    system_info.write(arch)
    if suname[0] == 'Linux':
        system_info.write('\n\n********** Linux distribution info **********\n\n')
        system_info.write(os.popen('lsb_release -a').read())


def networkConfig():
    """ Network configuration  """ 

    system_info.write('\n\n********** Network Config  **********\n\n')
    # we call different utilities for windows and "unix".
    if os.name == "posix":
        # if running as a non-root user, you may not have ifconfig in your path.
        # we'll attempt to guess where it is, and if we can't find it, just
        # assume that it is somewhere in your path.
        ifconfigCmd = '/sbin/ifconfig'
        if not os.path.exists(ifconfigCmd):
            ifconfigCmd = 'ifconfig'
        system_info.write(os.popen('%s -a' % ifconfigCmd).read())
    else:
        system_info.write(os.popen('ipconfig /all').read())


def networkStat():
    """ Network Status """ 

    system_info.write('\n\n********** Network Status **********\n\n')
    # just like with ifconfig, we attempt to guess the path of netstat.
    # if we can't find it, we leave it up to it being in your path.
    # also, if we're on windows, just go with the path-less command.
    netstatCmd = '/bin/netstat'
    if not os.name == "posix" or not os.path.exists(netstatCmd):
        netstatCmd = 'netstat'
    system_info.write(os.popen("%s -a -n" % netstatCmd).read())


def systemResources():
    """ System Memory """ 

    # on windows, we use msinfo to get all the relevant output.
    if os.name == "posix":
        system_info.write('\n\n********** System Ulimit **********\n\n')
        system_info.write(os.popen('ulimit -a').read())
        system_info.write('\n\n********** System Memory **********\n\n')
        suname = platform.uname()
        #SPL-17593
        if suname[0] == 'SunOS':
            system_info.write(os.popen('/usr/sbin/prtconf | head -3').read())
        elif suname[0] == 'Darwin':
            system_info.write(os.popen('vm_stat').read())
        elif suname[0] == 'Linux':
            system_info.write(os.popen('free').read())
        else:
            # try vmstat for hpux, aix, etc
            system_info.write(os.popen('vmstat').read())
        system_info.write('\n\n********** DF output **********\n\n')
        system_info.write(os.popen('df').read())
        system_info.write('\n\n********** mount output **********\n\n')
        system_info.write(os.popen('mount').read())
        system_info.write('\n\n********** cpu info **********\n\n')
        if suname[0] == 'SunOS':
            system_info.write(os.popen('/usr/sbin/psrinfo -v').read())
        elif suname[0] == 'Darwin':
            system_info.write(os.popen('system_profiler SPHardwareDataType').read())
        elif suname[0] == 'Linux':
            if os.path.exists('/proc/cpuinfo'):
                system_info.write(open('/proc/cpuinfo').read())
            else:
                system_info.write("/proc/cpuinfo unavailable. no /proc mounted?\n")
        elif suname[0] == 'AIX':
            aix_horror = """ for processor in `lsdev -c processor | awk '{ print $1; }'` ; do 
                                echo $processor;  
                                lsattr -E -l $processor; 
                             done """
            system_info.write(os.popen(aix_horror).read())
        elif suname[0] == 'FreeBSD':
            system_info.write(os.popen("sysctl -a | egrep -i 'hw.machine|hw.model|hw.ncpu'").read())
        elif suname[0] == 'HP-UX':
            hpux_horror = "echo 'selclass qualifier cpu;info;wait;infolog' | cstm"
            system_info.write(os.popen(hpux_horror).read())
        else:
            system_info.write("access to cpu data not known for platform.")
    else:
        os.popen('start /wait msinfo32.exe /report "%s" /categories +SystemSummary' % MSINFO_FILE)
        try:
            shutil.move(MSINFO_FILE, get_results_dir())
        except IOError, e: 
            # user probably clicked cancel on the msinfo gui
            err_msg = "Couldn't copy windows system info file to diag. %s"
            logging.warn(err_msg % (e.strerror,))

computed_db_paths = None
def splunkDBPaths():
    # if cached, return answer -- surprisingly computing this takes like 4 seconds
    global computed_db_paths
    if computed_db_paths:
        return computed_db_paths

    # first get all the index path config strings
    index_paths = []

    index_confs  = splunk.clilib.cli_common.getMergedConf('indexes')

    req_parm_warning = 'Indexing stanza [%s] is missing required parameter "%s"'

    volumes = {}
    pathKeys = ['homePath', 'coldPath', 'thawedPath']
    for stanza_name in index_confs.keys():
        if stanza_name == 'default':
            continue
        stanza = index_confs[stanza_name]
        # ignore disabled index stanzas
        if stanza.get('disabled') == "true":
            continue
        if stanza_name.startswith('volume:'):
            # skip broken volume groups
            if not stanza.has_key('path'):
                logging.warn("The indexing volume %s does not have a path defined, this is an error." % (stanza_name))
                continue
            volumes[stanza_name] = stanza['path']
        # ignore all virtual indexes for diag-building purposes, but warn if they seem broken
        elif stanza_name.startswith('provider-family:'):
            if not stanza.has_key('vix.mode'):
                logging.warn(req_parm_warning % (stanza_name, 'vix.mode'))
            if not stanza.has_key('vix.command'):
                logging.warn(req_parm_warning % (stanza_name, 'vix.command'))
            continue
        elif stanza_name.startswith('provider:'):
            if not stanza.has_key('vix.family'):
                logging.warn(req_parm_warning % (stanza_name, 'vix.family'))
            continue
        elif stanza.has_key("vix.provider"):
            logging.info('Virtual index "%s" found, not scanning for diag.' % stanza_name)
            continue
        # it's an index definition, get the paths
        else:
            for pathKey in pathKeys:
                if not stanza.has_key(pathKey):
                    logging.warn("The index %s does not have a value set for %s, this is unusual." % (stanza_name, pathKey))
                else:
                    index_paths.append(stanza.get(pathKey))

    def normalize_path(btool_path):
        # SPL-25568 first try to hack around use of '/' on Windows.. soo ugly
        # 'safe' because / is not legal path character on win32.  
        # bundle layer should normalize this to universal separator or
        # always platform specific.
        if os.name == "nt":
            btool_path = os.path.normpath(btool_path)

        # if it's absolute, there's no processing to do here.
        # (also fixes SPL-26129)
        if os.path.isabs(btool_path):
            return btool_path

        # btool normally gives us $VARS in the path (how it is in file)
        # This is clumsy but workable on unix, but nonfunctional on windows
        # so substitute the full path in there manually.  
        # Start by splitting the very first section of the path, and checking to
        # see if it's a unix variable.
        try:
            pathBegin, pathEnd = btool_path.split(os.path.sep, 1)
        except ValueError:
            err_mesg = "No directory separator found in index path: %s\n" % btool_path
            logging.error(err_mesg)
            if not system_info.closed:
                system_info.write(err_mesg)
            return None

        if pathBegin.startswith('$'):
            # if it does start with $, remove the $ and lookup the remainder in our env vars,
            # replacing the variable with the result.
            try:
                pathBegin = os.environ[pathBegin[1:]]
                # Some users are dumb enough to put mixed slashes in $SPLUNK_DB
                if os.name == 'nt':
                    pathBegin = os.path.normpath(pathBegin)
                # rebuild the path
                return os.path.join(pathBegin, pathEnd)
            except KeyError, key_e:
                # only log error, let dir or ls show the problem as well
                err_mesg = "No env var available from index path: %s\n" % key_e.args[0]
                logging.error(err_mesg)
                # hack fix for SPL-33455, instead should make errors file.
                if not system_info.closed:
                    system_info.write(err_mesg)

        return btool_path

    def expand_vol_path(orig_path, volumes=volumes):
        if not orig_path.startswith('volume:'):
            return orig_path
        tmp_path = orig_path
        if os.name == "nt" and  (not '\\' in tmp_path) and ('/' in tmp_path):
            tmp_path = orig_path.replace('/','\\')
        if not os.path.sep in tmp_path:
            logging.warn("Volume based path '%s' contains no directory seperator." % orig_path)
            return None
        volume_id, tail = tmp_path.split(os.path.sep, 1)
        if not volume_id in volumes:
            logging.warn("Volume based path '%s' refers to undefined volume '%s'." % (orig_path, volume_id))
            return None
        return os.path.join(volumes[volume_id], tail)

    # detect and expand volume paths


    paths = map(expand_vol_path, index_paths)
    paths = filter(None, paths) # remove chaff from expand_vol_path
    paths = map(normalize_path, paths)
    paths = filter(None, paths) # remove chaff from normalize_paths

    # cache answer
    computed_db_paths = paths

    return paths

def splunkDBListing(options):
    """ Index Listing Output""" 
    system_info.write('\n\n********** find **********\n')

    if options.index_listing == 'none':
        system_info.write("index_files diag option set to 'none', so there is no listing.\n")
        return

    db_paths = splunkDBPaths()

    if options.index_listing == "light":
        system_info.write("index_files diag option set to 'light_listing', only showing contents of hot buckets.\n")

        if os.name == "posix":
            dir_cmd = ["ls", "-l"]
            start_shell = False
        else:
            dir_cmd = ["dir", "/a"]
            start_shell = True

        for db_path in db_paths:
            cmd_args = dir_cmd + [db_path] 
            as_string = " ".join(cmd_args)
            system_info.write(as_string + "\n")

            p = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, 
                                 shell=start_shell)
            out, err = p.communicate()
            system_info.write(out + "\n")
            if err:
                system_info.write("Command listing command returned error text!\n")
                system_info.write(err + "\n")

            # Get contents of hot dirs for stuff like throttling!
            try:
                entries = os.listdir(db_path)
            except OSError, e:
                template = "Could not get entries for directory '%s' referenced by index configuration: got system error: %s\n"
                msg = template % (db_path, e)
                system_info.write(msg)
                logging.warn(msg)
                continue
            hot_entries = filter(lambda s: s.startswith("hot_"), entries)
            for hot in hot_entries:
                hot_path = os.path.join(db_path, hot)
                if not os.path.isdir(hot_path):
                    continue
                cmd_args = dir_cmd + [hot_path] 
                p = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, 
                                     shell=start_shell)

                as_string = " ".join(cmd_args)
                system_info.write(as_string + "\n")

                out, err = p.communicate()
                system_info.write(out + "\n")
                if err:
                    system_info.write("Command listing command returned error text!\n")
                    system_info.write(err + "\n")
        return

    system_info.write("showing full index content listing.\n")

    for db_path in db_paths:
        if os.name == "posix":
            # get a recursive listing of that path.
            system_info.write('\nls -lR "%s"\n' % db_path)
            system_info.write(os.popen('ls -lR "%s"' % db_path).read())
        else:
            system_info.write(os.popen('dir /s/a "%s"' % db_path).read())

def get_recursive_dir_info(dir_path, dest_file):
    """ do a recursive listing of the given dir and write the results on the given file """
    try:
        if not os.path.exists(os.path.dirname(dest_file)):
            os.makedirs(os.path.dirname(dest_file)) 
        f = open(dest_file, 'w') 
    except IOError, e: 
        # report fail, but continue along
        err_msg = "Error creating dirlisting file for '%s' at '%s', %s, continuing..."
        logging.warn(err_msg % (dir_path, dest_file, e.strerror))
        return
    try:
       if os.name == "posix":
          f.write("ls -lR \"%s\"\n" % dir_path)
          f.write(os.popen("ls -lR \"%s\"" % dir_path).read())
       else:
          f.write("dir /s/a \"%s\"\n" % dir_path)
          f.write(os.popen("dir /s/a \"%s\"" % dir_path).read())
    finally: 
       f.close()

def get_bucketmanifest_filenames(path):
    """return relative paths for all .bucketManifest files under a given path (hopefully a SPLUNK_DB or index)
     reqested by vishal, SPL-31499"""

    manifest_filename = ".bucketManifest"
    bucket_path = os.path.join(path, manifest_filename)
    if os.path.exists(bucket_path):
        return [bucket_path]
    else:
        return []

def get_worddata_filenames(path):
    "return relative paths for Host/Source/SourceTypes .data files under a given path (hopefully a SPLUNK_DB or index)"
    # rip off any trailing slashes to make the relative_dir hack work
    sepchars = os.path.sep 
    if os.path.altsep:
        sepchars += os.path.altsep
    path = path.rstrip(sepchars)

    filenames = []
    wanted_filenames = ("Hosts.data", "Sources.data", "SourceTypes.data")

    for dir, subdirs, files in os.walk(path):
        data_files = filter(lambda f: f in wanted_filenames, files)
        relative_dir = dir[len(path)+1:] # haaack
        # prepend the directory
        paths = map( lambda fname: os.path.join(relative_dir, fname), data_files)
        filenames.extend(paths)
    return filenames

###################
# internal utility

def copytree_special(src, dst, symlinks=False, ignore=None):
    """shutil.copytree safe for named pipes and other shenanigans"""
    special_files = []
    def special_file_filter(directory, dir_contents, prior_ignore=ignore,
                            special_files=special_files):
        # first we give any prior ignorer a chance to prune the listing
        logging.debug('dir_contents at start of copytree:' + str(dir_contents))
        if prior_ignore:
            ignore_files = prior_ignore(directory, dir_contents)
            logging.debug('prior ignore eliminated:' + str(ignore_files))
            # remember all those ignored files
            map(lambda f: add_excluded_file(os.path.join(directory, f)), ignore_files)
        else:
            ignore_files = []
        for filename in dir_contents:
            if filename in ignore_files:
                continue
            logging.debug('checking file: ' + filename)
            f_path = os.path.join(directory, filename)
            try:
                f_stat = os.lstat(f_path)
            except Exception, e:
                err = "Encountered failure attempting to get file type info for %s, (%s), will not capture"
                logging.error(err % (f_path, str(e)))
                ignore_files.append(filename)
                add_excluded_file(filename)
                continue # DO NOT KEEP
            if stat.S_ISLNK(f_stat.st_mode):
                continue # KEEP.  symlink flag on copytree dictates policy
            elif stat.S_ISSOCK(f_stat.st_mode):
                special_files.append(('socket', f_path))
            elif stat.S_ISCHR(f_stat.st_mode) or stat.S_ISBLK(f_stat.st_mode):
                special_files.append(('device', f_path))
            elif stat.S_ISFIFO(f_stat.st_mode):
                special_files.append(('fifo', f_path))
            elif stat.S_ISDIR(f_stat.st_mode) or stat.S_ISREG(f_stat.st_mode):
                continue # KEEP
            else:
                raise AssertionError("%s stat was not any known kind of file" % f_path)
            # reached end, so goes on ignore list
            ignore_files.append(filename)
            add_excluded_file(filename)
        logging.debug('returning:' + str(ignore_files))
        return ignore_files
    def make_fake_special_file(f_type, f_path, src_dir, dst_dir):
        tgt_path = os.path.join(dst_dir, f_path + '.' + f_type)
        tgt_dir = os.path.dirname(tgt_path)
        if not os.path.exists(tgt_dir):
            os.makedirs(tgt_dir)
        open(tgt_path, 'w') # make zero byte file, immediately closed
        shutil.copystat(os.path.join(src_dir, f_path), tgt_path)

    copy_errors = None
    try:
        shutil.copytree(src, dst, symlinks, special_file_filter)
    except shutil.Error, copy_errors:
        pass
    for f_type, f_path in special_files:
        try:
            make_fake_special_file(f_type, f_path, src, dst)
        except IOError, e:
            err_msg = "Error creating fake special file for '%s', %s, continuing..."
            logging.warn(err_msg % (f_path, e.strerror))
    if copy_errors:
        raise copy_errors # pylint: disable-msg=E0702
        # apparently pylint cannot understand 'if'
    return

def copy_file_with_parent(src_file, dest_file):
    "copy a file while creating any parent directories for the target"
    # ensure directories exist
    dest_dir = os.path.dirname(dest_file)
    try:
        if not os.path.isdir(dest_dir):
            os.makedirs(os.path.dirname(dest_file))
        shutil.copy(src_file, dest_file)
    except IOError, e:
        # windows sucks
        err_msg = "Error duping file for '%s' to '%s', %s, continuing..."
        logging.warn(err_msg % (src_file, dest_file, e.strerror))

def copy_indexfiles(target_path, level="full"):
    "copy index files such as .data and .bucketmanifest in all indices to the results dir"

    # nothing was wanted, so do nothing.
    if level in ("none", "light_listing"):
        return

    indexdata_filenames = []

    for dbPath in splunkDBPaths():
        if level == "full":
            rel_paths = get_worddata_filenames(dbPath)
            rel_paths.extend(get_bucketmanifest_filenames(dbPath))
        elif level in ("manifests", "manifest"):
            rel_paths = get_bucketmanifest_filenames(dbPath)
        else:
            raise Exception("Invalid value for index_level: %s" % level)
        # make absolute paths
        abs_paths = map(lambda f: os.path.join(dbPath, f), rel_paths)
        indexdata_filenames.extend(abs_paths)

    for src_file in indexdata_filenames:
        dest_file = src_file

        # trim SPLUNK_HOME from target directory
        if dest_file.startswith(SPLUNK_HOME):
                dest_file = dest_file[len(SPLUNK_HOME):]

        # windows tomfoolery....
        # make an informative path to store the indexdata file
        if os.name != 'posix':
            unc, dest_file = os.path.splitunc(dest_file)
            # yank initial backslashes off UNC expression for constructing
            # relative path later
            unc_dirnames = unc.lstrip('\\')
        else:
            unc_dirnames = ''
        # capture drive letter if exists
        drive , dest_file = os.path.splitdrive(dest_file)
        if drive:
            # letter only, since windows is unahppy with colons in dirnames
            drive = drive[0]

        # make relative, for join to work
        if dest_file[0] in (os.sep, os.altsep):
            dest_file = dest_file[1:]

        dest_file = os.path.join(target_path, unc_dirnames, drive, dest_file)

        copy_file_with_parent(src_file, dest_file)

def copy_dispatch_dir(target_path):
     dispatch_dir = os.path.join(SPLUNK_HOME, "var", "run", "splunk", "dispatch") 
     dispatch_dir = bless_long_path(dispatch_dir)
    
     # collect info iff dispatch dir is present
     if not os.path.exists(dispatch_dir):    
         return
 
     get_recursive_dir_info(dispatch_dir,  os.path.join(target_path, "dir_info.txt")) 
     for job in os.listdir(dispatch_dir):
         try:
             job_dir = os.path.join(dispatch_dir, job)
             if not os.path.isdir(job_dir):
                continue
             
             get_recursive_dir_info(job_dir, os.path.join(target_path, job, "dir_info.txt"))
             # copy only files in the job's dir, skip all the .gz stuff
             for f in os.listdir(job_dir):
                src_file = os.path.join(job_dir, f)
                # don't block forever reading from named pipes and so on.
                if not os.path.isfile(src_file):
                    continue
                # don't capture the customer's data, or zero byte status indicator files.
                if f.endswith('.gz') or f.startswith('results') or f.endswith(".token"):
                    continue
                       
                copy_file_with_parent(src_file, os.path.join(target_path, job, f)) 
         except OSError, e: 
             # report fail, but continue along
             err_msg = "Error capturing data for dispatch job dir '%s', %s, continuing..."
             logging.warn(err_msg % (job_dir, e.strerror))
             pass

def copy_pooled_data():
    # maybe get 'pooled' or searchhead pooling config data
    pooled_path = None
    try:
        pooled_path = splunk.clilib.bundle_paths.get_shared_storage()
    except AttributeError:
        pass

    if not pooled_path:
        return

    logging.info("Copying Splunk search-head pooled data...")

    try:
        # use copytree(..., ignore=func ) pattern here, but not elsewhere since
        # pooling feature only exists with newer splunk + newer python
        shutil.copytree(os.path.join(pooled_path), os.path.join(get_results_dir(), "search_pool"), symlinks = True, ignore=shutil.ignore_patterns('results.csv*', 'results_preview.csv*', '*.token', 'events', 'buckets', 'tsidxstats', '*.tsidx', '.snapshot'))
    except shutil.Error, copy_errors:
        # If files get moved or whatever during copy (like someone is moving
        # manager) this can happen
        msg = "Some problems were encountered copying the pooled config dir (likely these are not a problem):\n" + str(copy_errors)
        logging.warn(msg)

def copy_win_checkpoints():
    "get the checkpoint files used by windows inputs"
    p_storage = os.path.join("var", "lib", "splunk", "persistentStorage")
    checkpoint_files = ["wmi_checkpoint", "regmon-checkpoint"]
    checkpoint_dirs = ["WinEventLog", "ADmon"]

    for c_file in checkpoint_files:
        c_path = os.path.join(p_storage, c_file)
        src = os.path.join(SPLUNK_HOME, c_path)
        tgt = os.path.join(get_results_dir(), c_path)
        if os.path.exists(src):
            copy_file_with_parent(src, tgt)

    for c_dir in checkpoint_dirs:
        c_dir_path = os.path.join(p_storage, c_dir)
        src = os.path.join(SPLUNK_HOME, c_dir_path)
        tgt = os.path.join(get_results_dir(), c_dir_path)
        if os.path.exists(src):
            try:
                copytree_special(src, tgt)
            except shutil.Error, copy_errors:
                msg = "Some problems were encountered copying windows checkpoint files for '%s' :%s"
                logging.warn(msg % (c_dir, str(copy_errors)))

def deleteTree(path):
    """ Delete a directory, if it exists. """
    def handle_readonly_filedir_errors(func_called, path, exc):
        "try to make this more like rm -rf"
        error_type = exc[1]
        full_perms = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO

        parent = os.path.dirname(path)
        os.chmod(parent, full_perms)
        os.chmod(path, full_perms)
        if func_called == os.rmdir:
            os.rmdir(path)
        elif func_called == os.remove:
            os.remove(path)
        else:
            raise
    if os.path.isdir(get_results_dir()):
        shutil.rmtree(get_results_dir(), onerror=handle_readonly_filedir_errors)

def clean_temp_files():
    if os.path.isdir(RESULTS_LOC):
        for f in os.listdir(RESULTS_LOC):
            specific_tempdir = os.path.join(RESULTS_LOC, f)
            if os.path.isdir(specific_tempdir):
                deleteTree(specific_tempdir)

def local_getopt(file_options):

    def set_components(option, opt_str, value, parser):
        if not value:
            raise optparse.OptionValueError("--collect argument missing")

        components = value.split(",")
        all_components = set(KNOWN_COMPONENTS)
        if 'all' in components:
            parser.values.components = all_components
        else:
            req_components = set(components)
            unknown_components = req_components.difference(all_components)
            if unknown_components:
                as_string = ",".join(unknown_components)
                raise optparse.OptionValueError("Unknown components requested: " + as_string)
            parser.values.components = req_components

    def enable_component(option, opt_str, value, parser):
        component = value
        if component not in KNOWN_COMPONENTS:
            raise optparse.OptionValueError("Unknown component requested: " + component)
        elif component in parser.values.components:
            logging.warn("Requested component '%s' was already enabled.  No action taken." % component)
        else:
            parser.values.components.add(component)

    def disable_component(option, opt_str, value, parser):
        component = value
        if component not in KNOWN_COMPONENTS:
            raise optparse.OptionValueError("Unknown component requested: " + component)
        elif component not in parser.values.components:
            logging.warn("Requested component '%s' was already disabled.  No action taken." % component)
        else:
            parser.values.components.remove(component)

    # handle arguments
    parser = optparse.OptionParser()
    component_group = optparse.OptionGroup(parser, "Component Selection",
                      "These switches select which categories of information "
                      "should be collected.  The current components available "
                      "are: " + ", ".join(KNOWN_COMPONENTS))

    parser.add_option("--exclude", action="append", 
                      dest="exclude_list", metavar="pattern",
                      help="glob-style file pattern to exclude (repeatable)")

    component_group.add_option("--collect", action="callback", callback=set_components,
                      nargs=1, type="string", metavar="list",
                      help="Declare an arbitrary set of components to gather, as a comma-separated list, overriding any prior choices")
    component_group.add_option("--enable", action="callback", callback=enable_component,
                      nargs=1, type="string", metavar="component_name",
                      help="Add a component to the work list")
    component_group.add_option("--disable", action="callback", callback=disable_component,
                      nargs=1, type="string", metavar="component_name",
                      help="Remove a component from the work list")

    parser.add_option_group(component_group)

    detail_group = optparse.OptionGroup(parser, "Level of Detail",
                      "These switches cause diag to gather data categories "
                      "with lesser or greater thoroughness.")

    detail_group.add_option("--all-dumps", type="string", 
                      dest="all_dumps", metavar="bool",
                      help="get every crash .dmp file, opposed to default of a more useful subset")
    detail_group.add_option("--index-files", default="manifests", metavar="level",
                      help="Index data file gathering level: manifests, or full, meaning manifests + metadata files) [default: %default]")
    detail_group.add_option("--index-listing", default="light", metavar="level",
                      help="Index directory listing level: light (hot buckets only), or full, meaning all index buckets) [default: %default]")

    detail_group.add_option("--etc-filesize-limit", default=10000, type="int", metavar="kb",
                      help="do not gather files in $SPLUNK_HOME/etc larger than this many kilobytes, 0 disables this filter [default: %default]")
    detail_group.add_option("--log-age", default="60", type="int", metavar="days",
                      help="log age to gather: log files over this many days old are not included, 0 disables this filter [default: %default]")

    parser.add_option_group(detail_group)

    # get every category by default
    parser.set_defaults(components=set(KNOWN_COMPONENTS))

    # override above defaults with any from the server.conf file
    parser.set_defaults(**file_options)

    options, args =  parser.parse_args()

    if options.index_files not in ('manifests', 'manifest', 'full'):
        parser.error("wrong value for index-files: '%s'" % options.index_files)

    if options.index_listing not in ('light', 'full'):
        parser.error("wrong value for index-listing: '%s'" % options.index_listing)

    return options, args

def read_config():
    file_options = {}

    server_conf = splunk.clilib.cli_common.getMergedConf('server')
    diag_stanza = server_conf.get('diag', {})

    exclude_terms = [v for (k, v) in diag_stanza.items() if k.startswith("EXCLUDE")]
    file_options['exclude_list'] = exclude_terms

    other_settings = ("all_dumps", "index_files",  "log_age", "components")
    for setting in other_settings:
        if setting in diag_stanza:
            file_options[setting] = diag_stanza[setting]

    numeric_settings = ('log_age', 'etc_filesize_limit')
    for num_sett in numeric_settings:
        if num_sett in file_options:
            try:
                file_options[num_sett] = int(file_options[num_sett])
            except ValueError, e:
                msg = "Invalid value '%s' for %s, must be integer." 
                logging.error(msg % (file_options[num_sett], num_sett))
                raise

    if "components" in file_options:
        comp_list = file_options['components'].split(',')
        comp_list = map(lambda s: s.strip(), comp_list)
        all_components = set(KNOWN_COMPONENTS)
        if 'all' in comp_list:
            file_options['components'] = all_components
        else:
            wanted_components = set(comp_list)
            unknown_components = wanted_components.difference(all_components)
            if unknown_components:
                as_string = ",".join(unknown_components)
                msg = "Unknown components listed in server.conf: '%s'" % as_string
                logging.error(msg)
                raise ValueError(msg)
            file_options['components'] = wanted_components
    return file_options

def build_filename_filters(globs):
    if not globs:
        return []
    glob_to_re = lambda s: re.compile(fnmatch.translate(s))
    return map(glob_to_re, globs)

def filter_dumps(dump_filenames):
    class Dump:
        def __init__(self, filename):
            self.filename=filename
            self.stat = os.stat(filename)
    dumps = map(Dump, dump_filenames)
    total_dumpspace = sum(map(lambda d: d.stat.st_size, dumps))
    dump_megs = total_dumpspace / 1024 / 1024 
    if dump_megs >= 2000:
        logging.warn("""Note, you have %sMB in memory dump files in your $SPLUNK_HOME/var/log/splunk directory.  
You may want to prune, clean out, or move this data.""" % dump_megs)
    now = datetime.datetime.now()
    def age_filter(dump):
        age = now - datetime.datetime.fromtimestamp(dump.stat.st_mtime)
        if age.days >= 30:
            logging.error("Not including crashdump %s, over 30 days old" % dump.filename)
            return False
        return True
    dumps = filter(age_filter, dumps)
    # sort dumps by time, newest first.
    dumps.sort(cmp=lambda x, y: cmp(x.stat.st_mtime, y.stat.st_mtime))
    dumps.reverse()
    # try to get the useful crashes, starting with the two most recent.
    useful_crashes = dumps[:2] 
    # now get a third, going backwards if they are consective, to try to find
    # the start of whatever the recent problem is
    i = 2
    while i < len(dumps):
        cur_crash = dumps[i]
        if i+1 == len(dumps):
            # if we get to the end, use that
            useful_crashes.append(cur_crash)
            break
        cur_crashtime = datetime.datetime.fromtimestamp(cur_crash.stat.st_mtime)
        older_crashtime = datetime.datetime.fromtimestamp(dumps[i+1].stat.st_mtime)
        tdelta = cur_crashtime - older_crashtime
        # 2 days we assume is large enough to indicate this is the start
        if tdelta.days >= 2:
            useful_crashes.append(cur_crash)
            break
        i+=1
    return map(lambda x: x.filename, useful_crashes)

def copy_logs(options):
    # Weird implementation is to pass back the entries we DO NOT want; see python's shutil
    def ignore_filter(dir, entries, all_dumps=options.all_dumps, age_cutoff=options.log_age):
        age_cutoff_seconds = age_cutoff * 60 * 60 * 24 # days -> seconds
        do_not_want = []
        for ent in entries:
            if not all_dumps and ent.endswith(".dmp"):
                logging.debug('filtered out file for being a dump:' + ent)
                do_not_want.append(ent)
                continue
            elif options.log_age:
                path = os.path.join(dir, ent)
                if not os.path.isfile(path):
                    continue
                path_mtime = os.path.getmtime(path)
                age = time.time() - path_mtime 
                # if files are in future, get them anyway
                if age < age_cutoff_seconds:
                    continue
                logging.debug('filtered out file for being old:' + ent)
                do_not_want.append(ent)
        return do_not_want

    try:
        logdir = os.path.join(SPLUNK_HOME, "var", "log", "splunk")
        targetdir = os.path.join(get_results_dir(), "log")
        copytree_special(logdir, targetdir, symlinks = True, ignore = ignore_filter)
        if not options.all_dumps:
            # get a list of the dmp files, if any exist
            dumps = glob.glob(os.path.join(logdir, "*.dmp"))
            useful_dumps = filter_dumps(dumps)
            for dump in useful_dumps:
                shutil.copy(dump, targetdir)
    except shutil.Error, copy_errors:
        # log files might be rotated, I suppose?
        msg = "Some problems were encountered copying log files:\n" + str(copy_errors)
        logging.warn(msg)

    try:
        logdir = os.path.join(SPLUNK_HOME, 'var', 'log', 'introspection')
        targetdir = os.path.join(get_results_dir(), 'introspection')
        copytree_special(logdir, targetdir, symlinks = True)
    except shutil.Error, copy_errors:
        msg = 'Problems copying introspection logs:\n\t' + str(copy_errors)
        logging.warn(msg)


def copy_etc(options):
    filter_func = None

    if options.etc_filesize_limit:
        limit_in_bytes = options.etc_filesize_limit * (2**10)
        def filter_by_size(directory, entries, limit=limit_in_bytes):
            ignore_list = []
            for entry in entries:
                path = os.path.join(directory, entry)
                if os.path.isdir(path):
                    continue
                file_size = os.stat(path).st_size 
                if file_size > limit_in_bytes:
                    logging.info("filtered out file '%s'  limit: %s  size: %s" %
                                (path, limit, file_size))
                    ignore_list.append(entry)
            return ignore_list
        filter_func = filter_by_size
    try:
        etc_dir = os.path.join(SPLUNK_HOME, "etc")
        etc_dir = bless_long_path(etc_dir)
        copytree_special(etc_dir, os.path.join(get_results_dir(), "etc"), symlinks = True, ignore=filter_func)
    except shutil.Error, copy_errors:
        # If files get moved or whatever during copy (like someone is moving
        # manager) this can happen
        msg = "Some problems were encountered copying etc/... (likely these are not a problem):\n" + str(copy_errors)
        logging.warn(msg)

def copy_scripts():
    try:
        src = os.path.join(SPLUNK_HOME, "share", "splunk", "diag", "scripts")
        dst = os.path.join(get_results_dir(), "scripts")
        copytree_special(src, dst)

        # hackkkkkk XXX ; tweak perms on tarfile insert
        execute_everyone = stat.S_IXUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IXGRP \
                         | stat.S_IXOTH | stat.S_IROTH

        for scriptname in os.listdir(dst):
            os.chmod(os.path.join(dst, scriptname), execute_everyone)

    except shutil.Error, copy_errors:
        # log files might be rotated, I suppose?
        msg = "Some problems were encountered copying scripts:\n" + str(copy_errors)
        logging.warn(msg)

def copy_manifests(target_dir):
    logging.info("Adding manifest files...")
    try:
        manifests = glob.glob(os.path.join(SPLUNK_HOME, "*manifest"))
        for manifest in manifests:
            tgt_path = os.path.join(target_dir, os.path.basename(manifest))
            shutil.copy(manifest, tgt_path)
    except IOError, e:
        logging.error("Failed to copy splunk manifeste files to diag.  Permissions may be wrong.")

#####
# Tracking for files we did not put in the diag, that we might have normally
# done
excluded_filelist = []
def reset_excluded_filelist():
    global excluded_filelist
    excluded_filelist = []

def add_excluded_file(path):
    excluded_filelist.append(path)

def get_excluded_filelist():
    return excluded_filelist

def write_excluded_filelist(excl_list, tfile):
    # build a string, this is gross and I should probably build a clever object
    # with a read method... later.
    buf = "\n".join(excl_list) + "\n"

    # at least free the memory
    reset_excluded_filelist()

    tinfo = tarfile.TarInfo("%s/%s" % (get_diag_name(), "excluded_filelist.txt"))
    tinfo.size = len(buf)
    tinfo.mtime = time.time()
    fake_file = StringIO.StringIO(buf)
    tfile.addfile(tinfo, fileobj=fake_file)

def create_diag(options, log_buffer):
    reset_excluded_filelist()

    try:
        logging.info("Ensuring clean temp dir...")
        # delete any old results tarball, and create a fresh results directory
        clean_temp_files()
    except Exception, e:
        logging.error("""Couldn't initally clean diag temp directory.  
To work around move %s aside, or delete it.
A listing of the entire contents of this directory will help us identify the problem.""" % get_results_dir())
        raise

    os.makedirs(get_results_dir())
    if os.path.exists(get_tar_name()):
        os.unlink(get_tar_name())
    
    # make sure it's a supported os.
    if not os.name in ("posix", "nt"):
        logging.error("Unsupported OS (%s)." % os.name)
        write_logger_buf_on_fail(log_buffer) 
        sys.exit(1)

    logging.info("Starting splunk diag...")

    try:
        try:
            global system_info
            system_info = open(os.path.join(get_results_dir(), SYSINFO_FILE), 'w')
        except IOError:
            logging.error("Exiting: Cannot create system info file.  Permissions may be wrong.")
            write_logger_buf_on_fail(log_buffer) 
            sys.exit(1)

        logging.info("Getting system info...")
        # who is running me?
        sytemUsername()

        #get the splunk version
        splunkVersion()
        
        #uname
        systemUname()
        
        #ifconfig
        networkConfig()
        
        #netstat
        networkStat()
        
        #ulimit
        systemResources()

        if 'index_listing' in options.components:
            #ls
            logging.info("Getting index listings...")
            splunkDBListing(options)
        else:
            logging.info("Skipping index listings...")
    finally:
        system_info.close()
    
    if not 'etc' in options.components:
        logging.info("Skippping Splunk configuration files...")
    else:
        #copy etc and log into results too
        logging.info("Copying Splunk configuration files...")
        copy_etc(options)

    if not 'log' in options.components:
        logging.info("Skipping Splunk log files...")
    else:
        logging.info("Copying Splunk log files...")
        copy_logs(options)

    if not 'pool' in options.components:
        logging.info("Skipping Search Pool files...")
    else:
        logging.info("Copying Search Pool files...")
        copy_pooled_data()

    if not 'index_files' in options.components:
        logging.info("Skipping index files...")
    else:
        if options.index_files == "full":
            logging.info("Copying index worddata, and bucket info files...")
        else:
            logging.info("Copying bucket info files...")
        copy_indexfiles(get_results_dir(), options.index_files)

    # There's no need to make this a component, it's a single file
    if not os.path.exists(COMPOSITE_XML):
        logging.warn("Unable to find composite.xml file, product has likely not been started.")
    else:
        try:
            shutil.copy(COMPOSITE_XML, get_results_dir())
        except IOError, e:
            # windows sucks
            err_msg = "Error copying in composite.xml: '%s' continuing..."
            logging.warn(err_msg % e.strerror)

    if not 'dispatch' in options.components:
        logging.info("Skipping Splunk dispatch files...")
    else:
        logging.info("Copying Splunk dispatch files...")
        copy_dispatch_dir(os.path.join(get_results_dir(), "dispatch"))

    # again.. so small...
    if os.name == "nt":
        logging.info("Copying windows input checkpoint files...")
        copy_win_checkpoints()

    copy_scripts()

    copy_manifests(get_results_dir())

    filter_list = build_filename_filters(options.exclude_list)
    def tar_exclude(filename):
        for regex in filter_list:
            if regex.match(filename):
                add_excluded_file(filename)
                return True # don't tar
        return False

    #create a tar.gz file out of the results dir
    logging.info("Creating archive file...")
    # use gzip default compression level of 6 for (much more) speed
    destFile = tarfile.TarFile.gzopen(get_tar_name(), 'w', compresslevel=6)
    destFile.add(get_results_dir(), get_diag_name(), exclude=tar_exclude)

    write_excluded_filelist(get_excluded_filelist(), destFile)

    tinfo = tarfile.TarInfo("%s/%s" % (get_diag_name(), "diag.log"))
    tinfo.size = log_buffer.len
    tinfo.mtime = time.time()
    log_buffer.seek(0)
    destFile.addfile(tinfo, fileobj=log_buffer)

    destFile.close()

def setup_buffer_logger():
    "Creates and returns a StringIO object which will receive all the logged mesages during run"
    str_io_buf = StringIO.StringIO()
    s_io_handler = logging.StreamHandler(str_io_buf)
    s_io_fmtr = logging.Formatter('%(asctime)s: %(message)s', '%d/%b/%Y:%H:%M:%S')
    s_io_handler.setFormatter(s_io_fmtr)
    root_logger = logging.getLogger()
    root_logger.addHandler(s_io_handler)
    return str_io_buf

def write_logger_buf_on_fail(buf):
    "On failure, try to capture the logged messages somewhere that they won't be mutilated"
    tf = tempfile.NamedTemporaryFile(prefix="diag-fail-", suffix='.txt', delete=False)
    logging.info("Diag failure, writing out logged messages to '%s', please send output + this file to either an existing or new case ; http://www.splunk.com/support" % tf.name)
    tf.write(buf.getvalue())
    tf.close()

def main():
    # setup in-memory log holder to write out upon completion/termination
    log_buffer =  setup_buffer_logger()

    # handle options
    file_options = read_config()
    options, args = local_getopt(file_options)

    logging.info("The full set of options was: %s" % options)
    logging.info("The set of requested components was: %s" % sorted(list(options.components)))

    # Do the work, trying to ensure the temp dir gets cleaned even on failure
    try:
        create_diag(options, log_buffer)
    except Exception, e:
        logging.error("Exception occurred while generating diag, we are deeply sorry.")
        logging.error(traceback.format_exc())
        # this next line requests a file to be logged, not sure of clearest order
        write_logger_buf_on_fail(log_buffer) 
        logging.info("We will now try to clean out the temp directory...")
        clean_temp_files()
        return

    # and for normal conclusion..
    try:
        #clean up the results dir
        logging.info("Cleaning up...")
        clean_temp_files()
    finally:
        logging.info("Splunk diagnosis file created: %s" % get_tar_name())


def pclMain(args, fromCLI):
    return main()

#######
# test code from here.

class Test_Paths(object):
    # the tars won't even unpack on windows .. sigh
    test_dir = '/home/jrodman/p4/splunk/branches/ace/src/framework/tests/diag'

    @classmethod
    def fake_home_path(cls):
        return os.path.join(cls.test_dir, 'fake_splunkhome')
    @classmethod
    def output_dir_path(cls):
        return os.path.join(cls.test_dir, 'resultsdir')
    @classmethod
    def log_archive_path(cls):
        return os.path.join(cls.test_dir, 'logdir.tar.gz')
    @classmethod
    def index_archive_path(cls):
        return os.path.join(cls.test_dir, 'index.tar.gz')
    @classmethod
    def dispatch_archive_path(cls):
        return os.path.join(cls.test_dir, 'dispatch.tar.gz')

def prep_fakehome(tar_name):
    clean_fakehome() # in case of prior crash or whatever

    tar_path = os.path.join(Test_Paths.test_dir, tar_name)
    t = tarfile.open(tar_path)
    t.extractall(path=Test_Paths.fake_home_path())
    t.close()
    for root, dirs, files in os.walk(Test_Paths.fake_home_path()):
        for f in files:
            path = os.path.join(root, f)
            os.utime(path, None) # None == set to current time

def clean_fakehome():
    for item in os.listdir(Test_Paths.fake_home_path()):
        path = os.path.join(Test_Paths.fake_home_path(), item)
        shutil.rmtree(path)

def clean_resultsdir():
    for item in os.listdir(Test_Paths.output_dir_path()):
        path = os.path.join(Test_Paths.output_dir_path(), item)
        shutil.rmtree(path)

def clean_all():
    clean_fakehome()
    clean_resultsdir()

# util function
def sysinfo_test(f):
    # mock up the output systeminfo file
    global system_info
    system_info = StringIO.StringIO()
    f()
    return system_info.getvalue()

def test_username():
    output = sysinfo_test(sytemUsername)
    # assertions
    if "launched by" in output:
        return True
    else:
        msg = "bad output: '%s' " % output
        print msg,
        return False

def test_sversion():
    output = sysinfo_test(splunkVersion)
    # assertions
    if "Splunk" in output and "build" in output:
        return True
    else:
        print "bad output", output, 
        return False

def test_copylogs():
    prep_fakehome('logdir.tar.gz') # setup

    global get_results_dir
    global SPLUNK_HOME

    # provide mock values/interfaces to implementation
    prev_splunkhome = SPLUNK_HOME
    prev_get_results_dir = get_results_dir
    SPLUNK_HOME = Test_Paths.fake_home_path()
    # replace function with ours which gives our desired value
    get_results_dir = lambda: Test_Paths.output_dir_path()

    class fake_options:
        all_dumps = False
        log_age = 0 # no age filter, tar test file is static for one thing

    # run action
    copy_logs(fake_options)

    # turn off mocks
    SPLUNK_HOME = prev_splunkhome
    get_results_dir = prev_get_results_dir


    # assertions
    files_copied = os.listdir(os.path.join(Test_Paths.output_dir_path(), 'log'))
    dumps_copied = filter(lambda fn: fn.endswith(".dmp"), files_copied)

    clean_all() # ghetto teardown

    if len(files_copied) != 41: # maybe too brittle? based on tar contents
        sys.stderr.write("files copied: %i %s\n" % (len(dumps_copied), repr(dumps_copied)))
        return False

    if len(dumps_copied) == 3:
        return True
    else:
        sys.stderr.write("dumps copied: %i %s\n" % (len(dumps_copied), repr(dumps_copied)))
        return False

def test_dispatch():
    prep_fakehome('dispatch.tar.gz') # setup

    # mocks on
    global SPLUNK_HOME
    prev_splunkhome = SPLUNK_HOME
    SPLUNK_HOME = Test_Paths.fake_home_path()

    # copy_dispatch_dir copies where its told
    copy_dispatch_dir(os.path.join(Test_Paths.output_dir_path(), "dispatch"))

    # turn off mocks
    SPLUNK_HOME = prev_splunkhome

    test_ok = True
    # assertions
    should_exist = [
       os.path.join('dispatch','dir_info.txt'),
       os.path.join('dispatch','1279236202.117', 'dir_info.txt'),
       os.path.join('dispatch','1382938923.8084', 'search.log'),
       os.path.join('dispatch','1382938923.8084', 'dir_info.txt'),
       os.path.join('dispatch','1382938923.8084', 'timeline.csv'),
       os.path.join('dispatch','1382938923.8084', 'args.txt'),
       os.path.join('dispatch','1382938923.8084', 'custom_prop.csv')
    ]

    should_not_exist = [
       # don't get their data in the info buckets
       os.path.join('dispatch','1382938923.8084', 'buckets', '0.000_0.000.csv'),
       os.path.join('dispatch','1382938923.8084', 'buckets'),
       # or in the output
       os.path.join('dispatch','1382938923.8084', 'results.csv_preview.csv'),
       # or in the events piles
       os.path.join('dispatch','1382938923.8084', 'events'),
       # also don't try to read pipes and hang
       os.path.join('dispatch','1382938923.8084', 'alive.token')
    ]

    for rel_p in should_exist:
        path = os.path.join(Test_Paths.output_dir_path(), rel_p)
        if not os.path.exists(path):
            sys.stderr.write("file missing: %s\n" % path)
            test_ok = False
    for rel_p in should_not_exist:
        path = os.path.join(Test_Paths.output_dir_path(), rel_p)
        if os.path.exists(path):
            sys.stderr.write("file missing: %s\n" % path)
            test_ok = False

    return test_ok

def test_indexes():
    prep_fakehome('index.tar.gz') # setup

    # mocks on
    global SPLUNK_HOME
    global splunkDBPaths

    prev_splunkhome = SPLUNK_HOME
    SPLUNK_HOME = Test_Paths.fake_home_path()

    prev_splunkdb_paths = splunkDBPaths 
    splunkDBPaths = lambda : [os.path.join(SPLUNK_HOME, 'var','lib','fakeindex')]

    # fire functionality
    copy_indexfiles(Test_Paths.output_dir_path())

    # turn off mocks
    SPLUNK_HOME = prev_splunkhome
    splunkDBPaths = prev_splunkdb_paths

    test_ok = True
    # assertions
    should_exist = [
       os.path.join('var','lib', 'fakeindex', '.bucketManifest'),
       os.path.join('var','lib','fakeindex', 'db_4_5_0', 'Hosts.data'),
       os.path.join('var','lib','fakeindex', 'db_4_5_0', 'Sources.data'),
       os.path.join('var','lib','fakeindex', 'db_4_5_0', 'SourceTypes.data'),
       os.path.join('var','lib','fakeindex', 'hot_v1_1', 'Hosts.data'),
       os.path.join('var','lib','fakeindex', 'hot_v1_1', 'Sources.data'),
       os.path.join('var','lib','fakeindex', 'hot_v1_1', 'SourceTypes.data'),
    ]

    should_not_exist = [
       os.path.join('var','lib','fakeindex', 'db_4_5_0', 'Strings.data'),
       os.path.join('var','lib','fakeindex', 'hot_v1_1', 'Strings.data'),
    ]

    for rel_p in should_exist:
        path = os.path.join(Test_Paths.output_dir_path(), rel_p)
        if not os.path.exists(path):
            sys.stderr.write("file missing: %s\n" % path)
            test_ok = False
    for rel_p in should_not_exist:
        path = os.path.join(Test_Paths.output_dir_path(), rel_p)
        if os.path.exists(path):
            sys.stderr.write("file present that should not be: %s\n" % path)
            test_ok = False

    return test_ok

def run_tests():
    parser = optparse.OptionParser()
    parser.add_option("--dev-tests", action="store_true", dest="dev_tests")
    parser.add_option("--test-dir", type="string", dest="test_dir", 
                      help="working dir for the tests", metavar="path")
    options, args =  parser.parse_args()
    if options.test_dir:
        Test_Paths.test_dir = options.test_dir

    clean_all()


    for name, obj in filter(lambda n: n[0].startswith('test_'), globals().items()):
        # ensure we don't get non-functions
        if type(obj) != type(run_tests):
            sys.stderr.write("error: %s is not a function" % name)
            continue
        sys.stdout.write("running test: %s " % name)
        if obj():
            sys.stdout.write("OK\n")
        else:
            sys.stdout.write("FAIL\n")
        clean_all()

#######
# direct-run startup, normally splunk diag doesn't use this but 
# splunk cmd python info_gather.py goes through here.

if __name__ == "__main__":

    # Add this flag as a total hack so it doesn't come out in the documented
    # arguments..
    if "--dev-tests" in sys.argv:
        run_tests()
        exit()

    # get logging behavior similar to normal splunk invocation
    # logging apis suck, renaming them sucks more
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(message)s"))
    l = logging.getLogger()
    l.setLevel(logging.INFO)
    l.addHandler(sh)
    main()
