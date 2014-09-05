import sys
# import "os" very defensively -- this way we can try to work even if
# $PYTHON_PATH is not set correctly in the shell for the python we're
# running in:
try:
    import site, os
except ImportError:
    # NOTE: we can't "import os" yet so we can't use os.path
    # to do pathname manipulation.
    if sys.platform.startswith("win"):
        dir_sep = "\\"
        python_lib_subdir = "Python-" + sys.version[0:3] + "\\Lib"
    else:
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
import conf

def scrub(bnf):
    privatefields = ['maintainer', 'appears-in', 'note']
    for attrs,val in bnf.items():
        usage = val.get("usage", [""])[0].strip().lower()
        # remove any non-public commands
        if usage != "" and ("public" not in usage or "deprecated" in usage):
            del bnf[attrs]
        # remove private fields
        for p in privatefields:
            if p in val:
                del val[p]
    
if __name__ == '__main__':
    argc = len(sys.argv)
    argv = sys.argv
    if 2 <= argc <= 3:
        filename = argv[1]
        bnf = conf.ConfParser.parse(filename)
        scrub(bnf)
        outtext = conf.ConfParser.toString(bnf)        
        if argc == 3:
            outfilename = argv[2]
            outdir = os.path.split(outfilename)[0]
            if not os.path.isdir(outdir):
                os.makedirs(outdir)
            f = open(outfilename, 'w')
            f.write(outtext)
            f.close()
        else:
            print outtext
    else:
        print 'Usage:'
        print argv[0], "filename [outfilename]"

