#   Version 4.0
from __future__ import with_statement
from contextlib import closing, nested

import splunk
import splunk.clilib.cli_common as comm
import splunk.clilib.control_exceptions as cex
import splunk.rest.format as format
import control_exceptions as cex

import glob
import logging as logger
import os
import shutil
import tarfile
import tempfile
import time
import urllib2

join = os.path.join

def _bundle_error(msg):
    tmp = lit("ERROR_APP_INSTALL__S") % msg
    logger.error(tmp)
    raise splunk.InternalServerError(tmp)

def lit(name):
    """
    Get externalized string literals for use in this module.
    """
    try:
        return comm.getConfKeyValue("literals", "clilib.bundle_paths", name)
    except Exception, e:
        logger.exception(e)
        return ""

def get_shared_storage():
    """
    If search head pooling is enabled, return the location of shared storage.
    Otherwise, return an empty string.
    """
    try:
        state   = comm.getConfKeyValue('server', 'pooling', 'state')
        storage = comm.getConfKeyValue('server', 'pooling', 'storage')
        if ((state == 'enabled') and (len(storage) > 0)):
            return storage
    except Exception, e:
        pass
    return ''

#
# Bundle-related constants (accessed through functions)
#

def etc():
    return join(comm.splunk_home, "etc")

def get_legacy_base_path():
    return join(etc(), "bundles")

def get_shared_etc():
    storage = get_shared_storage()
    if len(storage) > 0:
        storage = join(storage, "etc")
    else:
        storage = etc()
    return storage
    
def get_base_path():
    storage = get_shared_etc()
    return join(storage, "apps")

def get_slaveapps_base_path():
    storage = get_shared_etc()
    return join(storage, "slave-apps")    
    
def get_system_bundle_path():
    return join(etc(), "system")

#
# Bundle-related path builders
#

def _name_to_subdir(filename):
    if filename.endswith(".conf"):
        dir = "local"
    elif filename.endswith(".py"):
        dir = "bin"
    else:
        dir = "static"
    return dir

def make_path(filename):
    return join(get_system_bundle_path(), _name_to_subdir(filename), filename)

def make_bundle_path(bundle, filename):
    return join(get_base_path(), bundle, _name_to_subdir(filename), filename)

def make_legacy_bundle_path(bundle, filename):
    # Legacy bundles don't have any directory structure in particular, so this
    # function is only marginally useful. It works for conf files, which have
    # traditionally been located at the base of each bundle directory.
    return join(get_legacy_base_path(), bundle, filename)

def get_bundle_subdirs(subdir):
    paths = [ ]
    for b in bundles_iterator(True):
        tmp = join(b.location(), subdir)
        if b.is_enabled() and os.path.isdir(tmp):
            paths.append(tmp)
    return paths

def make_bundle_install_path(bundle):
    return join(get_base_path(), bundle)

def make_legacy_bundle_install_path(bundle):
    return join(get_legacy_base_path(), bundle)

#
# Other bundle-related utilities
#

def get_app_name_from_tarball(path):
    appname = ""
    with closing(tarfile.open(path)) as tar:
        for i in tar.getmembers():
            logger.debug("Examining file to install: %s" % i.name)
            if os.path.isabs(i.name):
                _bundle_error(lit("ERROR_ARCHIVE_ABS_PATH"))
            path = i.name.split('/') # tar files always use '/' as the separator, irrespective of platform
            if len(path)>1 and not i.name.startswith('.'):
                appname = path[0]
                break
    if len(appname) == 0:
        _bundle_error(lit("ERROR_ARCHIVE_NO_APP"))
    return appname

def parse_boolean(parseMe):
    result = True
    try:
        asint = int(parseMe)
        result = (asint > 0)
    except:
        result = parseMe.lower().startswith(('t', 'y'))
    return result

################################################################################



class BundleException(cex.PCLException):
    pass
class BundleMissing(BundleException):
    pass
class BundleInvalidFileType(BundleException):
    pass
class BundleExportException(BundleException):
    pass



#
# BundleInstaller: install a bundle from a URL (e.g. SplunkBase).
#
#   installer = BundleInstaller(url)
#   bundle, statuscode = installer.install()
#
class BundleInstaller:

    # Status codes and their meanings.
    STATUS_UPGRADED = 200
    STATUS_INSTALLED = 201

    # Get and install a bundle using the given urllib2.Request object.
    # Return a (Bundle, status code) tuple.
    # NOTE: If an exception occurs, this method leaves behind temporary files,
    # possibly including a downloaded tar file and its extracted contents. We
    # purposely skip cleanup to allow for debugging.
    def install_from_url(self, req, force=False):
        try:
            fd, tmppath = tempfile.mkstemp()
            logger.debug("Using temporary fd %d at: %s" % (fd, tmppath))
            logger.debug("Checking for application at: %s" % req.get_full_url())
            with nested(closing(urllib2.urlopen(req)),
                        os.fdopen(fd, "w+")) as (remote, local):
                logger.debug("Downloading application from: %s" %
                             remote.geturl())
                logger.debug("URL metadata:\n%s" % remote.info())
                logger.debug("Downloading application to: %s" % tmppath)
                local.write(remote.read())
                local.flush()
                logger.debug("Application download complete: %d bytes",
                             os.path.getsize(tmppath))
            result = self.install_from_tar(tmppath, force)
            safe_remove(tmppath)
            return result
        except urllib2.HTTPError, e:
            logger.exception(e)
            if (e.code == 403) :
                raise splunk.AuthorizationFailed(e.msg)
            else :
                raise splunk.ResourceNotFound(e.msg)

    # Install the bundle stored within the tar archive at the given path.
    # Return a (Bundle, status code) tuple.
    def install_from_tar(self, path, force=False):
        logger.debug("Examining application archive: %s" % path)    
        if not os.path.exists(path) or os.path.isdir(path):
            raise splunk.ResourceNotFound('The package "%s" wasn\'t found' % path)

        tmpdir = None
        appname = get_app_name_from_tarball(path)
        existing = get_bundle(appname)
        if not force and existing:
            msg = 'App "%s" already exists; use the "-%s true" argument to install anyway' % (appname, 'update')
            raise splunk.RESTException(409, msg)        
        with closing(tarfile.open(path)) as tar:
            tmpdir = tempfile.mkdtemp()
            logger.debug("Extracting application to: %s" % tmpdir)
            tar.extractall(tmpdir, members=self._filter_tar(tar))
        result = self.install_from_dir(tmpdir, appname)
        safe_remove(tmpdir)
        return result

    # Install the bundle stored within the directory at the given path.
    # Return a (Bundle, status code) tuple.
    def install_from_dir(self, path, appname, cleanup=True):
        tmp = Bundle(appname, os.path.join(path, appname))
        if get_bundle(appname) is None:
            status = self.STATUS_INSTALLED
        else:
            status = self.STATUS_UPGRADED
        tmp.install(cleanup)
        return (get_bundle(appname), status)

    def _filter_tar(self, members):
        for tarinfo in members:
            # skip hidden files and dirs
            if '/.' in tarinfo.name:
                continue
            yield tarinfo
        



#
# Bundle: manipulate a bundle on the local filesystem.
#
# Use get_bundle(), bundles_iterator(), or BundleInstaller.install() to get a
# Bundle instance. Don't call the Bundle constructor directly unless you know
# what you're doing.
#
class Bundle:

    # useful constants
    _DEFAULT = "default"
    _LOCAL = "local"

    def __init__(self, name, location):
        self._rawname = name
        self._name = os.path.normcase(name)
        self._location = os.path.normpath(location)
        self._metadata = BundleMetadata(self)

    def _verify(self):
        location = self.location()
        if location is None:
            raise BundleMissing(self.name())
        if not os.path.isdir(location):
            raise BundleInvalidFileType(location)

    def ctime(self):
        return os.path.getctime(self.location())

    def name(self, raw=False):
        if raw:
            return self._rawname
        return self._name

    def location(self):
        return self._location

    def is_enabled(self):
        try:
            self._verify()
        except:
            return False
        return self._metadata.is_bundle_enabled()

    # Return the text of the README file in this bundle.
    def description(self):
        text = ""
        try:
            with open(os.path.join(self.location(), "README")) as f:
                text = f.read()
        except:
            pass
        return text

    # Generate an AtomEntry from this bundle.
    def to_atom(self, id, link=None):
        self._verify()
        results = { }
        results["enabled"] = self.is_enabled()
        self._metadata.update_out(results)
        return format.AtomEntry(id,
                                title=self.prettyname(),
                                updated=format.strftime(time.localtime(self.ctime())),
                                link=link,
                                contentType="text",
                                rawcontents=results,
                                summary=self.description())

    def enable(self):
        self._verify()
        return self._metadata.enable_bundle()

    def disable(self):
        self._verify()
        return self._metadata.disable_bundle()

    def delete(self):
        self._verify()
        comm.removeItem(self.location())
        self._location = None

    def migrate(self, dryRun=False):
        self._verify()
        if not self.is_legacy():
            return
        name = self.name()
        src = self.location()
        cleanup = True
        if (name == self._DEFAULT) or (name == "README"):
            logger.notice(lit("INFO_MIGRATE_OMIT__S") % name)
        elif name == self._LOCAL:
            if not dryRun:
                self._rearrange_conf_files(self._LOCAL)
            comm.mergeDirs(src, get_system_bundle_path(), dryRun, self._merger)
        else:
            if not dryRun:
                self._rearrange_conf_files(self._DEFAULT)
            collision = get_bundle(name)
            if collision is None:
                comm.moveItem(src, make_bundle_install_path(name), dryRun)
                cleanup = False
            else:
                logger.notice(lit("INFO_MIGRATE_COLLISION__S_S") %
                              (collision.name(), collision.location()))
                logger.notice(lit("INFO_MIGRATE_OMIT__S") % name)
        if cleanup and not dryRun:
            logger.info(lit("INFO_MIGRATE_CLEANUP__S") % src)
            self.delete()

    def _merger(self, src, dst, dryRun):
        try:
            if dryRun:
                # Be less verbose for dry runs. More detailed information is
                # likely to be misleading because of dry run limitations.
                logger.notice(lit("INFO_MIGRATE_MOVE_DRYRUN__S") % src)
                return
            root, ext = os.path.splitext(src)
            if ext == ".conf":
                if os.path.lexists(dst):
                    # Combine src and dst confs; don't override anything in dst.
                    combinedConf = comm.readConfFile(src)
                    dstConf = comm.readConfFile(dst)
                    for k in dstConf.keys():
                        if combinedConf.has_key(k):
                            combinedConf[k].update(dstConf[k])
                        else:
                            combinedConf[k] = dstConf[k]
                    # In case we don't have permission to truncate the
                    # file, just remove it preemptively.
                    safe_remove(dst)
                    logger.notice(lit("INFO_MIGRATE_MERGE_CONF__S_S") % (src, dst))
                    comm.writeConfFile(dst, combinedConf)
                else:
                    comm.copyItem(src, dst)
            else:
                if os.path.lexists(dst):
                    logger.notice(lit("INFO_MIGRATE_IGNORE_DUP__S_S") % (src, dst))
                else:
                    comm.copyItem(src, dst)
        except Exception, e:
            logger.warn(lit("WARN_MIGRATE_NO_CREATE__S") % dst)
            logger.exception(e)

    def install(self, cleanup=True):
        self._verify()
        if self.is_installed():
            return
        src = self.location()
        collision = get_bundle(self.name())            
        
        if collision is None:
            dst = make_bundle_install_path(self._rawname)
            if cleanup:
                comm.moveItem(src, dst)
            else:
                comm.mkdirItem(dst)
                comm.mergeDirs(src, dst)
        else:
            default_path = os.path.join(collision.location(), self._DEFAULT)
            if os.path.exists(default_path):
                default_path_bkup = "%s.old.%s" % (default_path, time.strftime("%Y%m%d-%H%M%S", time.localtime()))
                comm.moveItem(default_path, default_path_bkup)
                comm.mkdirItem(default_path)
            self._rearrange_conf_files(self._DEFAULT)
            comm.mergeDirs(src, collision.location())

            if cleanup:
                self.delete()

    # Move conf files at the base of the bundle into a subdirectory.
    def _rearrange_conf_files(self, dirname):
        self._verify()
        location = self.location()
        subdir = os.path.join(location, dirname)
        if os.path.lexists(subdir):
            if not os.path.isdir(subdir):
                raise OSError("Existing file not a directory: %s" % subdir)
        else:
            comm.mkdirItem(subdir)
        for f in glob.glob(os.path.join(location, "*.conf")):
            comm.moveItem(f, subdir)

    # Is this bundle installed?
    def is_installed(self):
        self._verify()
        return (self.is_system() or
                (os.path.dirname(self.location()) == get_base_path()))

    # Is this a legacy bundle?
    def is_legacy(self):
        self._verify()
        return (os.path.dirname(self.location()) == get_legacy_base_path())

    # Is this bundle the system bundle?
    def is_system(self):
        return (self.location() == get_system_bundle_path())

    # Return the expected path to <filename> in this bundle.
    def _name_to_expected_path(self, filename):
        if self.is_legacy():
            return os.path.join(self.location(), filename)
        else:
            return os.path.join(self.location(),
                                _name_to_subdir(filename),
                                filename)

    # Export files specified in <filenames> to <export_dir>.
    def do_export(self, filenames, export_dir):
        self._verify()
        # Don't export any legacy bundle except the local bundle.
        if (self.is_legacy() and (self.name() != self._LOCAL)):
            logger.info(lit("INFO_EXPORT_OMIT__S") % self.location())
            return
        to_backup = [ ]
        for name in filenames:
            path = self._name_to_expected_path(name)
            if os.path.isfile(path):
                to_backup.append(path)
        if len(to_backup) == 0:
            logger.debug("Nothing to export from application: %s" % self.name())
            return
        if not maybe_makedirs(export_dir):
            raise BundleExportException("Cannot set up directory: %s" %
                                        export_dir)
        for path in to_backup:
            logger.info(lit("INFO_EXPORT_FILE__S") % path)
            shutil.copy(path, export_dir)

    # Import the files in <import_dir> into this bundle.
    def do_import(self, import_dir):
        if not os.path.isdir(import_dir):
            logger.debug("Nothing to import into application: %s" % self.name())
            return
        for name in os.listdir(import_dir):
            src = os.path.join(import_dir, name)
            dst = self._name_to_expected_path(name)
            logger.info(lit("INFO_IMPORT_FILE__S") % dst)
            head, tail = os.path.split(dst)
            maybe_makedirs(head, True)
            shutil.copy(src, dst)

    def set_postinstall_metadata(self, dict):
        self._metadata.set_postinstall_metadata(dict)

    def prettyname(self):
        prettyname = self._metadata.get_prettyname()
        if prettyname is None:
            return self.name()
        else:
            return prettyname

    # Is this bundle overriden by another bundle with the same name?
    def is_overridden(self):
        return ((not self.is_legacy()) and
                os.path.isdir(make_legacy_bundle_install_path(self.name())))



#
# Metadata about a given bundle.
#
class BundleMetadata:
    # constants from BundlesIterator.cpp
    _MANIFEST = "MANIFEST"
    _STANZA_INSTALL = "install"
    _KEY_STATE = "state"
    _STATE_ENABLED = "enabled"
    _STATE_DISABLED = "disabled"

    PRETTYNAME = "prettyName"

    def __init__(self, bundle):
        self._dict = { }
        self._dict[self._STANZA_INSTALL] = { }
        try:
            base = bundle.location()
            self._manifest_writable = join(base, Bundle._LOCAL, self._MANIFEST)
            self._manifest_install = join(base, Bundle._DEFAULT, self._MANIFEST)
            all_candidates = [ self._manifest_writable,
                               self._manifest_install,
                               join(base, self._MANIFEST) ]
            # find actual MANIFEST to read
            for candidate in all_candidates:
                if os.path.isfile(candidate):
                    self._dict = comm.readConfFile(candidate)
                    break
        except:
            pass
    
    def update_out(self, copy):
        try:
            copy.update(self._dict[self._STANZA_INSTALL])
        except Exception, e:
            logger.error(lit("ERROR_METADATA_WRITE"))
            logger.exception(e)
            pass

    def is_bundle_enabled(self):
        try:
            state = self._dict[self._STANZA_INSTALL][self._KEY_STATE]
            if state == self._STATE_DISABLED:
                return False
        except:
            pass
        return True

    def enable_bundle(self):
        if self.is_bundle_enabled():
            return
        self._dict[self._STANZA_INSTALL][self._KEY_STATE] = self._STATE_ENABLED
        self._commit_metadata(self._manifest_writable)

    def disable_bundle(self):
        if not self.is_bundle_enabled():
            return
        self._dict[self._STANZA_INSTALL][self._KEY_STATE] = self._STATE_DISABLED
        self._commit_metadata(self._manifest_writable)

    def _commit_metadata(self, path):
        maybe_makedirs(os.path.dirname(path), True)
        comm.writeConfFile(path, self._dict)

    def set_postinstall_metadata(self, dict):
        self._dict = { self._STANZA_INSTALL : dict }
        self._commit_metadata(self._manifest_install)

    def get_prettyname(self):
        try:
            return self._dict[self._STANZA_INSTALL][self.PRETTYNAME]
        except Exception, e:
            return None



#
# Wrappers around bundle import and export functionality.
#

class BundlesExporter:
    def do_export(self, filenames, site):
        for b in bundles_iterator(True):
            b.do_export(filenames, site.bundle_to_subsite(b))

class BundlesImporter:
    def do_import(self, site):
        for b in bundles_iterator(True):
            b.do_import(site.bundle_to_subsite(b))

class BundlesImportExportSite:
    def __init__(self, dir):
        self.dir = dir
    def bundle_to_subsite(self, b):
        if b.is_system():
            return self.system()
        elif b.is_legacy():
            return os.path.join(self.legacy(), b.name())
        else:
            return os.path.join(self.base(), b.name())
    def base(self):
        return self._setup("apps_backup")
    def system(self):
        return self._setup("system_backup")
    def legacy(self):
        return self._setup("legacy_backup")
    def _setup(self, subdir):
        tmp = os.path.join(self.dir, subdir)
        if maybe_makedirs(tmp):
            return tmp
        else:
            return None



################################################################################

#
# Get a Bundle object corresponding to the bundle with the given name.
#
def get_bundle(name, unmanaged=False):
    nname = os.path.normcase(name)
    for b in bundles_iterator(unmanaged):
        if b.name() == nname:
            return b
    return None

#
# Get a Bundle object corresponding to the bundle with the given pretty name.
#
# Passing check_override=False causes this function to return a Bundle even if
# it is overridden by another Bundle.
#
def get_bundle_by_prettyname(name, check_override=True):
    if check_override:
        iter = bundles_iterator_overrides
    else:
        iter = bundles_iterator
    for b in iter():
        if b.prettyname() == name:
            return b
    return None

#
# Iterate over all locally-installed bundles, excluding bundle archives.
#
# Passing unmanaged=True causes this iterator to return Bundles that aren't
# normally managed as Applications. This includes the system bundle and legacy
# bundles (i.e. old-style bundles in the legacy bundle location).
#
def bundles_iterator(unmanaged=False):
    if unmanaged:
        path = get_system_bundle_path()
        head, name = os.path.split(path)
        yield Bundle(name, path)
    basedirs = [ get_base_path() ]
    if unmanaged:
        basedirs.append(get_legacy_base_path())
    for base in basedirs:
        if not os.path.exists(base) or not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            path = os.path.join(base, name)
            if os.path.isdir(path):
                yield Bundle(name, path)

#
# Iterate over bundles that are not overridden by other bundles.
#
def bundles_iterator_overrides():
    for b in bundles_iterator():
        if not b.is_overridden():
            yield b

#
# Delete without worrying about if the path is None, if it actually exists, if
# it's a directory/regular file/symlink, etc.
#
def safe_remove(path):
    try:
        if (path is not None) and os.path.lexists(path):
            comm.removeItem(path)
    except Exception, e:
        logger.debug("Unable to delete: %s" % path)
        logger.exception(e)

#
# Make a directory if it doesn't already exist. Return false on error, e.g. if
# a non-directory file at <path> already exists.
#
# Only throw exceptions if throw_exceptions = True.
#
def maybe_makedirs(path, throw_exceptions=False):
    try:
        if os.path.exists(path):
            return os.path.isdir(path)
        else:
            os.makedirs(path)
            return True
    except Exception, e:
        if throw_exceptions:
            raise
        else:
            logger.debug("Unable to makedirs: %s" % path)
            logger.exception(e)
            return False

#
# Return the first directory in this path as read from left to right,
# e.g. '/foo/bar/baz' -> 'foo'.
#
def first_path_piece(path):
    prev = ""
    cur = os.path.normpath(path)
    while len(cur) > 0:
        prev = cur
        cur = os.path.dirname(prev)
    return prev

################################################################################



def migrate_bundles(args, fromCLI):
    ARG_DRYRUN = "dry-run"
    ARG_NAME = "name"
    comm.validateArgs(( ), (ARG_NAME, ARG_DRYRUN), args)
    isDryRun = comm.getBoolValue(ARG_DRYRUN, args.get(ARG_DRYRUN, "false"))
    name = args.get(ARG_NAME)
    found = False
    logger.info(lit("INFO_MIGRATE_START__S") % name)
    for b in bundles_iterator(True):
        if b.is_legacy() and ((name is None) or (name == b.name())):
            b.migrate(isDryRun)
            found = True
    if name and (not found):
        raise cex.ArgError, "Cannot find a legacy bundle named '%s'." % name
    else:
        logger.info(lit("INFO_MIGRATE_END__S") % name)

def warn_about_legacy_bundles(dryRun):
    if dryRun:
        return
    # Prepend warnings to each conf file in the legacy local bundle.
    CONF_WARN = "# %s" % lit("WARN_MIGRATE_CONF")
    for path in glob.glob(make_legacy_bundle_path("local", "*.conf")):
        try:
            with open(path, "r") as f:
                text = f.read()
            if text.startswith(CONF_WARN):
                continue
            text = CONF_WARN + text
            with open(path, "w") as f:
                f.write(text)
        except Exception, e:
            logger.exception(e)
    # Issue a warning about each legacy bundle.
    legacy = [ b for b in bundles_iterator(True) if b.is_legacy() ]
    # Issue a deprecation warning.
    if len(legacy) > 0:
        logger.warn(lit("WARN_MIGRATE_DEP"))
        for b in legacy:
            logger.warn("\t%s", b.location())
