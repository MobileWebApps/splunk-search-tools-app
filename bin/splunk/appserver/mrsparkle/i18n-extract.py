#!/opt/splunk/bin/python
#
# Extracts text to be translated from python, javascript and mako templates
# and compiles it into a .pot file
#
# also stores all strings found in .js files in a python pickle cache file
# to accelerate lookup times from splunkweb


# On windows we might get run with "python -S" so we can try to
# set the path ourselves if "import site" fails. If it fails assume
# that we're trying to use SPLUNK_HOME's python and just didn't have
# PYTHONPATH set up yet
import sys
try:
    import site, os, os.path
except ImportError:
    # NOTE: we can't "import sys" yet so we can't use sys.path
    # to do pathname manipulation.
    if sys.platform.startswith("win"):
        dir_sep = "\\"
        python_lib_subdir = "Python-" + sys.version[0:3] + "\\Lib"
    else:
        # This code isn't as useful on UNIX since "make" will invoke
        # python via /usr/bin/env, but just in case...
        dir_sep = "/"
        python_lib_subdir = "lib/python-" + sys.version[0:3]
    # sys.executable is %SPLUNK_HOME%\bin\python.exe, so strip two
    # path elements off it and then append new_path_elem
    new_path_elem = sys.executable
    for tmp in xrange(0, 2):
       new_path_elem = new_path_elem[0:new_path_elem.rfind(dir_sep)]
    new_path_elem += dir_sep + python_lib_subdir
    sys.path += [ new_path_elem ]
    import site, os

import sys, os.path, time
from cStringIO import StringIO
from babel.messages import frontend
from babel.messages.pofile import unescape
import babel.util
import babel.messages.extract
import cPickle as pickle

HEADER = u"""\
# Translations for Splunk
# Copyright (C) 2005-%(year)s Splunk Inc. All Rights Reserved.
""" % {'year': time.strftime('%Y') }

def processFilename(line):
    fn = line[2:].rsplit(':',1)[0].strip() # split off the line number
    try:
        # strip the relative portion of the filename
        fn = fn[fn.rindex('../')+3:]
    except ValueError:
        pass
    # hack for search_mrsparkle directories
    if fn.startswith('web/'):
        fn = fn[4:]
    return fn


# Really ugly hack to exclude contrib paths from being extracted
def custom_pathmatch(pattern, filename):
    if 'contrib/' in filename or 'contrib\\' in filename:
        return False
    return babel.util.pathmatch(pattern, filename)
babel.messages.extract.pathmatch = custom_pathmatch


def main():
    if not os.path.isdir('locale'):
        script_dir = os.path.dirname(os.path.realpath(__file__))
        os.chdir(script_dir)

    if len(sys.argv) == 1:
        locale_dir = 'locale'
    elif len(sys.argv) == 2:
        locale_dir = sys.argv[1]
    else:
        print "Usage: i18n-extract.py [<locale path>]"
        sys.exit(1)

    locale_dir = os.path.realpath(locale_dir)
    splunk_home = os.environ.get('SPLUNK_HOME')
    if not splunk_home:
        print "SPLUNK_HOME environment variable was not set!"
        sys.exit(2)

    print locale_dir
    print splunk_home
    if locale_dir.startswith(splunk_home):
        strip = splunk_home.replace(os.path.sep, '/')
        strip = (strip+'/share/splunk', strip, 'etc/apps/')
        template_dir = os.path.join(splunk_home, 'share/splunk/search_mrsparkle')
        default_dir = os.path.join(splunk_home, 'etc/system/default')
        search_app = os.path.join(splunk_home, 'etc/apps/search')
        launcher_app = os.path.join(splunk_home, 'etc/apps/launcher')
        getting_started_app = os.path.join(splunk_home, 'etc/apps/gettingstarted')
        stubby_app = os.path.join(splunk_home, 'etc/apps/stubby')
        datapreview_app = os.path.join(splunk_home, 'etc/apps/splunk_datapreview')
    else:
        # assume this is an extraction from the source tree
        strip = ('../../../../web', '../../../../', 'cfg/bundles/')
        template_dir = '../../../../web/search_mrsparkle'
        default_dir = '../../../../cfg/bundles/default'
        search_app = '../../../../cfg/bundles/search'
        launcher_app = '../../../../cfg/bundles/launcher'
        getting_started_app = '../../../../cfg/bundles/gettingstarted'
        stubby_app = '../../../../cfg/bundles/stubby'
        datapreview_app = '../../../../cfg/bundles/splunk_datapreview'

    # this is always relative to the script directory
    search_helper_dir = '../../searchhelp'


    args = [
        'extract',
        '-F',  os.path.join(locale_dir, 'babel.cfg'),
        '-c', 'TRANS:',
        '-k', 'deferred_ugettext',
        '-k', 'deferred_ungettext',
        '.',
        template_dir,
        default_dir,
        search_app,
        launcher_app,
        getting_started_app,
        datapreview_app
        #stubby_app
        ]


    sys.argv[1:] = args

    # Open the .pot file for write
    outfile = open(os.path.join(locale_dir, 'messages.pot'), 'w')

    # Capture Babel's stdout so we can translate the absolute pathnames into relative ones
    buf = StringIO()
    stdout_org = sys.stdout
    sys.stdout = buf

    # Do the extraction
    frontend.main()

    # restore stdout
    sys.stdout = stdout_org

    # Start reading the captured data from the top
    buf.reset()

    print >>outfile, HEADER
    currentfn = []
    filemapping = {}
    msgid = msgid_plural = None
    for line in buf:
        line = line.strip()
        if line.startswith('# '):
            # strip the original comment header
            continue
        if line[:3] != '#: ': # filename:linenum references begin with #:
            print >>outfile, line
            if currentfn:
                # capture the translation associated with the current filename(s)
                if line.startswith('msgid '):
                    msgid = unescape(line[6:])
                elif line.startswith('msgid_plural '):
                    msgid_plural = unescape(line[13:])
                elif line.startswith('"'):
                    # multi-line translation
                    if msgid is not None:
                        msgid = msgid + unescape(line)
                    elif msgid_plural is not None:
                        msgid_plural = msgid_plural + unescape(line)
            continue
        if msgid and currentfn:
            for fn in currentfn:
                fn = fn.lower()
                if fn.find('data' + os.sep + 'ui') > -1:
                    fn = os.path.splitext(os.path.basename(fn))[0]
                filemapping.setdefault(fn, []).append( (msgid, msgid_plural) )
            msgid = msgid_plural = None
            currentfn = []
        newline = '#: '
        fnpairs = line[3:].split(' ')
        for fnpair in fnpairs:
            fn, ln = fnpair.rsplit(':', 1)
            for prefix in strip:
                if fn.startswith(prefix):
                    fn = fn[len(prefix):].strip('/')
            # keep track of js files
            if fn.endswith('.js') or fn.find('data' + os.sep + 'ui') > -1:
                currentfn.append(fn)
            newline += "%s:%s " % (fn, ln)
        print >>outfile, newline
    outfile.close()

    # collect the final message
    if msgid and currentfn:
        for fn in currentfn:
            if fn.find('data' + os.sep + 'ui') > -1:
                fn = os.path.splitext(os.path.basename(fn))[0]
            filemapping.setdefault(fn.lower(), []).append( (msgid, msgid_plural) )

    # pickle the lookup data
    cachefile = open(os.path.join(locale_dir, "messages-filecache.bin"), 'wb')
    pickle.dump(filemapping, cachefile, 2)
    cachefile.close()

if __name__=='__main__':
    main()
