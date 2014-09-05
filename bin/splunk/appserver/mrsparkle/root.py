#!/usr/bin/python

import __main__
import os
import sys
import splunk


# Windows specific paths which are different from *nix os's:
# Windows:  $SPLUNK_HOME/Python2.5/Lib
# *nix:     $SPLUNK_HOME/lib/python2.5
SPLUNK_SITE_PACKAGES_PATH = os.path.dirname(os.path.dirname(splunk.__file__))


# define filepath for logging files
BASE_LOG_PATH = os.path.join('var', 'log', 'splunk')

# define fallback filepath for UI module assets
FAILSAFE_MODULE_PATH = os.path.join('share', 'splunk', 'search_mrsparkle' ,'modules')

# define the fallback root URI
FAILSAFE_ROOT_ENDPOINT = '/'

# define the fallback static rss URI
FAILSAFE_RSS_DIR = 'var/run/splunk/rss'

# define fallback static root URI
FAILSAFE_STATIC_DIR = 'share/splunk/search_mrsparkle/exposed'

# define fallback testing resource root URI
FAILSAFE_TESTING_DIR = 'share/splunk/testing'

# define logging configuration
LOGGING_DEFAULT_CONFIG_FILE = os.path.join(os.environ['SPLUNK_HOME'], 'etc', 'log.cfg')
LOGGING_LOCAL_CONFIG_FILE = os.path.join(os.environ['SPLUNK_HOME'], 'etc', 'log-local.cfg')
LOGGING_STANZA_NAME = 'python'
LOGGING_FORMAT = "%(asctime)s %(levelname)-s\t[%(requestid)s] %(module)s:%(lineno)d - %(message)s"

# Set a limit on how much data we're prepared to receive (in MB)
DEFAULT_MAX_UPLOAD_SIZE = 500 

IS_CHERRYPY = True
__main__.IS_CHERRYPY = True # root.py is not always __main__


#
# init base logger before all imports
#

import logging, logging.handlers, sys

# this class must be defined inline here as importing it from appserver.* will
# cause other loggers to be bound to the wrong class
class SplunkLogger(logging.Logger):
    """
    A logger that knows how to make our custom Cherrypy requestid available to
    the handler's log formatter
    """
    def makeRecord(self, name, level, fn, lno, msg, args, exc_info, func=None, extra=None):
        try:
            from splunk.appserver.mrsparkle.lib.util import get_request_id
            if extra is None:
                extra = {}
            extra['requestid'] = get_request_id()
        except ImportError, e:
            extra = {'requestid': '-'}
        return logging.Logger.makeRecord(self, name, level, fn, lno, msg, args, exc_info, func, extra)


logging.setLoggerClass(SplunkLogger)
logger = logging.getLogger('splunk')
logger.setLevel(logging.INFO)
splunk_log_handler = logging.handlers.RotatingFileHandler(os.path.join(os.environ['SPLUNK_HOME'], BASE_LOG_PATH, 'web_service.log'), mode='a') # will set limits/thresholds later
splunk_log_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
logger.addHandler(splunk_log_handler)


# lock down lxml per SPL-31061
import lxml.etree
class NullResolver(lxml.etree.Resolver):
    def resolve(self, url, public_id, context):
        logger.debug("Ignoring request for lxml external entity url=%s public_id=%s context=%s" % (url, public_id, context))
        return self.resolve_string('', context)

class SafeXMLParser(lxml.etree.XMLParser):
    """An XML Parser that ignores requests for external entities"""
    def __init__(self, *a, **kw):
        super(SafeXMLParser, self).__init__(*a, **kw)
        self.resolvers.add(NullResolver())
        
parser = SafeXMLParser()
lxml.etree.set_default_parser(parser)
lxml.etree.UnsafeXMLParser = lxml.etree.XMLParser
lxml.etree.XMLParser = SafeXMLParser



try:
    splunk.setupSplunkLogger(logger, LOGGING_DEFAULT_CONFIG_FILE, LOGGING_LOCAL_CONFIG_FILE, LOGGING_STANZA_NAME)


    #
    # continue importing
    #

    import re, time, shutil, hashlib
    import splunk.clilib.cli_common
    import splunk.clilib.bundle_paths
    import splunk.util, splunk.entity
    from controllers.top import *
    import cherrypy
    from lib.util import make_absolute, splunk_to_cherry_cfg, get_rss_parent_dir, make_splunkhome_path, is_encrypted_cert
    from lib import i18n, filechain, error, startup
    from lib.customlogmanager import SplunkedLogManager
    from splunk.appserver.mrsparkle.lib import module
    from splunk.util import normalizeBoolean

    # override Cherrypy's default staticdir handler so we can handle things like custom module locations
    import lib.customstaticdir

    # Make sure CherryPy doesn't shutdown if the user logs out of Windows
    try:
        #pylint: disable=F0401
        import win32con
        win32con.CTRL_LOGOFF_EVENT = object()
    except ImportError:
        pass

    # override Cherrypy's default session locking behaviour
    import lib.sessions


    # replace CherryPy's LogManager class with our subclassed one
    from cherrypy import _cplogging
    _cplogging.LogManager = SplunkedLogManager
    cherrypy.log = _cplogging.LogManager()
    def _cp_buslog(msg, level):
        logger.log(level, 'ENGINE: %s' % msg)

    cherrypy.engine.unsubscribe('log', cherrypy._buslog)
    cherrypy.engine.subscribe('log', _cp_buslog)

    # import our custom pid-file writing plugin
    from lib.custompidfile import ProcessID

    # define etc, site-packages and share/search/mrsparkle in a os agnostic way:
    SPLUNK_ETC_PATH = make_splunkhome_path(['etc'])
    SPLUNK_MRSPARKLE_PATH = make_splunkhome_path(['share', 'search', 'mrsparkle'])

    # define filepath for pid file
    PID_PATH = make_splunkhome_path(['var', 'run', 'splunk', 'splunkweb.pid'])

    # define filepath where compiled mako templates are stored
    MAKO_CACHE_PATH = make_splunkhome_path(['var', 'run', 'splunk', 'mako_cache'])

    class RootController(BaseController):
        """This controller is only used if the site root is something other than /"""
        @expose
        def index(self):
            raise cherrypy.HTTPRedirect(cherrypy.config['root_endpoint'])



    def mount_static(ctrl, global_cfg, cfg):
        static_endpoint = global_cfg['static_endpoint']
        static_app_dir= make_absolute('etc/apps', '')

        # resolver for static content bundled with applications
        def static_app_resolver(section, branch, dir):
            """ Resolver that pulls application specific assets. """

            parts = branch.split('/')
            subbranch, app, asset = parts[0], parts[1], '/'.join(parts[2:] )
            appstaticdir = os.path.normpath(os.path.join(dir, app, 'appserver', 'static'))
            fn = os.path.normpath(os.path.join(appstaticdir, asset))

            if fn.startswith(appstaticdir) and fn.startswith(os.path.normpath(dir)) and os.path.exists(fn):
                sp = os.path.splitext(asset)
                if sp[1] == '.js' and not asset.startswith('js/contrib') and 'i18noff' not in cherrypy.request.query_string:
                    i18n_cache = i18n.translate_js(fn)
                    if i18n_cache:
                        return i18n_cache
                return fn

            return False

        def static_resolver(section, branch, dir):
            """resolver that knows how to add translations to javascript files"""

            # chain off to another resolver for statics served from application bundles.
            # overrides the 'dir' param with where applications are stored.
            if branch.startswith('app/'):
                return static_app_resolver(section, branch, static_app_dir)
            
            sp = os.path.splitext(branch)
            fn = os.path.join(dir, branch)
            if branch == 'js/i18n.js':
                return i18n.dispatch_i18n_js(fn) # send the locale data with the i18n.js system
            elif branch.endswith('common.min.js'):
                return filechain.chain_common_js() # returns the path to a cached file containing the finished cache file
            elif branch.startswith('js/splunkjs'):
                return False
            elif not branch.startswith('js/contrib') and sp[1] == '.js' and os.path.exists(fn) and 'i18noff' not in cherrypy.request.query_string:
                return i18n.translate_js(fn) # returns the path to a cached file containing the original js + json translation map
            return False # fallback to the default handler

        if (global_cfg.get('static_dir','') == '') :
            logger.warn('static endpoint configured, but no static directory. Falling back to ' + FAILSAFE_STATIC_DIR)
        staticdir = make_absolute(global_cfg.get('static_dir', FAILSAFE_STATIC_DIR), '')
        global_cfg['staticdir'] = staticdir
        
        cfg[static_endpoint] = {
            'tools.sessions.on' : False, # no session required for static resources
            'tools.staticdir.on' : True,
            'tools.staticdir.dir' : staticdir,
            'tools.staticdir.strip_version' : True,
            'tools.staticdir.resolver' : static_resolver,
            'tools.staticdir.content_types' : {
                'js' : 'application/javascript', 
                'css': 'text/css', 
                'cache': 'text/javascript', # correct python's application/x-javascript
                'woff': 'application/font-woff'
            },            
            'tools.gzip.on' : True,
            'tools.gzip.mime_types' : ['text/plain', 'text/html', 'text/css', 'application/javascript', 'application/x-javascript', 'text/javascript']
        }

        faviconFile = 'favicon.ico'
        if 'product_type' in cherrypy.config:
            if cherrypy.config['product_type'] == 'hunk':
                faviconFile = 'favicon_hunk.ico'

        ctrl.robots_txt = cherrypy.tools.staticfile.handler(os.path.join(staticdir, 'robots.txt'))
        ctrl.favicon_ico = cherrypy.tools.staticfile.handler(os.path.join(staticdir, 'img', faviconFile))


    def run(blocking=True):
        # get confs
        global_cfg = splunk_to_cherry_cfg('web', 'settings')

        # allow command line arguments to override the configuration
        # eg. --httpport=80
        args = util.args_to_dict()

        # splunkd proxied mode
        proxied_arg = args.get('proxied')
        global_cfg['is_proxied'] = False
        if proxied_arg:
            del args['proxied']
            proxied_parts = proxied_arg.split(',')
            if len(proxied_parts) == 2:
                proxied_ip_addr = proxied_parts[0]
                proxied_port = int(proxied_parts[1])
                logger.info('Proxied mode ip_address=%s port=%s:' % (proxied_ip_addr, proxied_port))
                global_cfg['is_proxied'] = True
                global_cfg['startwebserver'] = 1
                global_cfg['httpport'] = proxied_port
                global_cfg['enableSplunkWebSSL'] = False
                global_cfg['remoteUser'] = 'REMOTE-USER'
                global_cfg['SSOMode'] = 'strict'
                global_cfg['trustedIP'] = proxied_ip_addr
                global_cfg['server.socket_host'] = proxied_ip_addr
            else:
                logger.warn("Proxied mode flag invalid '%s'. --proxied=' IP_ADDR PORT'" % proxied_arg)

        # debugging can be turned on from the command line with --debug
        if args.get('debug'):
            del args['debug']
            logger.setLevel(logging.DEBUG)
            for lname, litem in logger.manager.loggerDict.items():
                if not isinstance(litem, logging.PlaceHolder):
                    logger.debug("Updating logger=%s to level=DEBUG" % lname)   
                    litem.setLevel(logging.DEBUG)
            args['js_logger_mode'] = 'Server'
            args['js_no_cache'] = True
        global_cfg.update(args)

        # support SPLUNK_BINDIP backwards compatibly. -- overrides web.conf
        if (not global_cfg['is_proxied']) and os.environ.has_key('SPLUNK_BINDIP'):
            global_cfg['server.socket_host'] = os.environ['SPLUNK_BINDIP'].strip()

        global_cfg['server.socket_port'] = global_cfg['httpport']

        if normalizeBoolean(global_cfg.get('enableSplunkWebSSL', False)):
            logger.info('Enabling SSL')
            priv_key_path = str(global_cfg['privKeyPath'])
            ssl_certificate = str(global_cfg['caCertPath'])
            ssl_ciphers = str(global_cfg['cipherSuite'])

            if os.path.isabs(priv_key_path):
                global_cfg['server.ssl_private_key'] = priv_key_path
            else:
                global_cfg['server.ssl_private_key'] = make_splunkhome_path([priv_key_path])

            if os.path.isabs(ssl_certificate):
                global_cfg['server.ssl_certificate'] = ssl_certificate
            else:
                global_cfg['server.ssl_certificate'] = make_splunkhome_path([ssl_certificate])

            if not os.path.exists(global_cfg['server.ssl_private_key']):
                raise ValueError("%s Not Found" % global_cfg['server.ssl_private_key'])

            if not os.path.exists(global_cfg['server.ssl_certificate']):
                raise ValueError("%s Not Found" % global_cfg['server.ssl_certificate'])

            if global_cfg.get('supportSSLV3Only'):
                global_cfg['server.ssl_v3_only'] = True

            if ssl_ciphers:
                global_cfg['server.ssl_ciphers'] = ssl_ciphers
        else:
            # make sure the secure flag is not set on session cookies if we're not serving over SSL
            global_cfg['tools.sessions.secure'] = False

        # setup cherrypy logging infrastructure
        if global_cfg.has_key('log.access_file'):
            filename = make_absolute(global_cfg['log.access_file'], BASE_LOG_PATH)
            maxsize = int(global_cfg.get('log.access_maxsize', 0))
            maxcount = int(global_cfg.get('log.access_maxfiles', 5))
            if maxsize > 0:
                cherrypy.log.access_file = ''
                h = logging.handlers.RotatingFileHandler(filename, 'a', maxsize, maxcount)
                h.setLevel(logging.INFO)
                h.setFormatter(_cplogging.logfmt)
                cherrypy.log.access_log.addHandler(h)
                del global_cfg['log.access_file']
            else:
                global_cfg['log.access_file'] = filename

        if global_cfg.has_key('log.error_file'):
            # we've already committed to web_service.log by this point
            del global_cfg['log.error_file']
        cherrypy.log.error_file = ''
        cherrypy.log.error_log.addHandler(splunk_log_handler)
        if global_cfg.has_key('log.error_maxsize'):
            splunk_log_handler.maxBytes = int(global_cfg['log.error_maxsize'])
            splunk_log_handler.backupCount = int(global_cfg.get('log.error_maxfiles', 5))
            
        # now that we have somewhere to log, test the ssl keys. - SPL-34126
        # Lousy solution, but python's ssl itself hangs with encrypted keys, so avoid hang by
        # bailing with a message
        if global_cfg['enableSplunkWebSSL']:
            for cert_file in (global_cfg['server.ssl_private_key'], 
                              global_cfg['server.ssl_certificate']):
                if is_encrypted_cert(cert_file):
                    logger.error("""Specified cert '%s' is encrypted with a passphrase.  SplunkWeb does not support passphrase-encrypted keys at this time.  To resolve the problem, decrypt the keys on disk, generate new
passphrase-less keys, or disable ssl for SplunkWeb.""" % cert_file)
                    raise Exception("Unsupported encrypted cert file.")

        # set login settings
        if global_cfg.get('tools.sessions.storage_type') == 'file':
            global_cfg['tools.sessions.storage_path'] = make_absolute(global_cfg['tools.sessions.storage_path'])

        # SPL-16963: add port number to session key to allow for sessions for multiple
        # instances to run on a single host, without mutually logging each other out.
        global_cfg['tools.sessions.name'] = "session_id_%s" % global_cfg['httpport']
        global_cfg['tools.csrfcookie.name'] = "splunkweb_csrf_token_%s" % global_cfg['httpport']

        # set mako template cache directory
        global_cfg.setdefault('mako_cache_path', MAKO_CACHE_PATH)
        
        root_name = global_cfg.get('root_endpoint', FAILSAFE_ROOT_ENDPOINT).strip('/')
        
        ctrl = TopController()
        cfg = {'global' : global_cfg}

        # initialize all of the custom endpoints that are registered in the
        # apps
        ctrl.custom.load_handlers()


        # Serve static files if so configured
        if global_cfg.has_key('static_endpoint'):
            mount_static(ctrl, global_cfg, cfg)
        
        if global_cfg.has_key('testing_endpoint'):
            if (global_cfg.get('static_dir','') == '') :
                logger.warn('testing endpoint configured, but no testing directory. Falling back to ' + FAILSAFE_TESTING_DIR)
            staticdir = make_absolute(global_cfg.get('testing_dir', FAILSAFE_TESTING_DIR), '')

            cfg[global_cfg['testing_endpoint']] = {
                'tools.staticdir.on' : True,
                'tools.staticdir.dir' : staticdir,
                'tools.staticdir.strip_version' : True
            }
        
        if global_cfg.has_key('rss_endpoint'):
            logger.debug('Checking for shared storage location')
            rssdir = get_rss_parent_dir()
            if len(rssdir) > 0:
                logger.debug('Using shared storage location: %s' % rssdir)
            else:
                rssdir = make_absolute(global_cfg.get('rss_dir', FAILSAFE_RSS_DIR), '')
                logger.debug('No shared storage location configured, using: %s' % rssdir)
            cfg[global_cfg['rss_endpoint']] = {
                'tools.staticdir.on' : True,
                'tools.staticdir.dir' : rssdir,
                'tools.staticdir.strip_version' : False,
                'tools.staticdir.default_ext' : 'xml',
                'error_page.404': make_splunkhome_path([FAILSAFE_STATIC_DIR, 'html', 'rss_404.html'])
            }
            

        # Modules served statically out of /modules or out of an app's modules dir
        def module_resolver(section, branch, dir):
            from lib.apps import local_apps
            # first part of branch is the module name
            parts = os.path.normpath(branch.strip('/')).replace(os.path.sep, '/').split('/')
            locale = i18n.current_lang(True)
            if not parts:
                return False
            module_path = local_apps.getModulePath(parts[0])
            if module_path:
                # this means there is a module named parts[0]
                # SPL-51365 images should load irrespective of css_minification.
                if parts[0]==parts[1]:
                    # ignore of repetition of module name
                    # happens for image request when minify_css=False
                    fn = os.path.join(module_path, *parts[2:])
                else:
                    fn = os.path.join(module_path, *parts[1:])
                #verified while fixing SPL-47422
                #pylint: disable=E1103 
                if fn.endswith('.js') and os.path.exists(fn):
                    return i18n.translate_js(fn) # returns the path to a cached file containing the original js + json translation map
                return fn
            elif parts[0].startswith('modules-') and parts[0].endswith('.js'):
                hash = parts[0].replace('modules-', '').replace('.min.js', '')
                return make_absolute(os.path.join(i18n.CACHE_PATH, '%s-%s-%s.cache' % ('modules.min.js', hash, locale)))
            elif parts[0].startswith('modules-') and parts[0].endswith('.css'):
                return filechain.MODULE_STATIC_CACHE_PATH + os.sep + 'css' + os.sep + parts[0]
            return False

        moddir = make_absolute(global_cfg.get('module_dir', FAILSAFE_MODULE_PATH))
        cfg['/modules'] = {
            'tools.staticdir.strip_version' : True,
            'tools.staticdir.on' : True,
            'tools.staticdir.match' : re.compile(r'.*\.(?!html$|spec$|py$)'), # only files with extensions other than .html, .py and .spec are served
            'tools.staticdir.dir' : moddir,
            'tools.staticdir.resolver' : module_resolver,
            'tools.staticdir.content_types' : {'js' : 'application/javascript', 'css': 'text/css', 'cache': 'text/javascript'} # correct python's application/x-javascript
        }

        cfg['/'] = {
            'request.dispatch': i18n.I18NDispatcher(),
        }

        # enable gzip + i18n goodness
        if global_cfg.get('enable_gzip', False):
            cfg['/'].update({
                'tools.gzip.on' : True,
                'tools.gzip.mime_types' : ['text/plain', 'text/html', 'text/css', 'application/javascript', 'application/x-javascript', 'application/json'],
            })

        #cfg['/']['tools.gzip.on'] = False

        # Set maximum filesize we can receive (in MB)
        maxsize = global_cfg.get('max_upload_size', DEFAULT_MAX_UPLOAD_SIZE)
        cfg['global']['server.max_request_body_size'] = int(maxsize) * 1024 * 1024

        if global_cfg.get('enable_throttle', False):
            from lib import throttle
            cfg['global'].update({
                'tools.throttle.on' : True,
                'tools.throttle.bandwidth': int(global_cfg.get('throttle_bandwidth', 50)), 
                'tools.throttle.latency': int(global_cfg.get('throttle_latency', 100))
            })

        if global_cfg.get('enable_log_runtime', False):
            points = global_cfg.get('enable_log_runtime')
            if points == 'All': points = 'on_start_resource,before_request_body,before_handler,before_finalize,on_end_resource,on_end_request'
            if points is True: points = 'on_end_resource'
            for point in points.split(','):
                def log_closure(point):
                    def log():
                        import time
                        starttime = cherrypy.response.time
                        endtime = time.time()
                        delta = (endtime - starttime) * 1000
                        logger.warn('log_runtime point=%s path="%s" start=%f end=%f delta_ms=%.1f' % (point, cherrypy.request.path_info, starttime, endtime, delta))
                    return log
                setattr(cherrypy.tools, 'log_'+point, cherrypy.Tool(point, log_closure(point)))
                cfg['/']['tools.log_%s.on' % point] = True

        if global_cfg.get('storm_enabled'):
            from splunk.appserver.mrsparkle.lib.storm import hook_storm_session
            hook_storm_session()

        if global_cfg.get('override_JSON_MIME_type_with_text_plain', False):
            import splunk.appserver.mrsparkle
            splunk.appserver.mrsparkle.MIME_JSON = "text/plain; charset=UTF-8"
            logger.info("overriding JSON MIME type with '%s'" % splunk.appserver.mrsparkle.MIME_JSON)

        # setup handler to create and remove the pidfile
        pid_path = make_absolute(global_cfg.get('pid_path', PID_PATH))
        ProcessID(cherrypy.engine, pid_path).subscribe()


        #
        # process splunkd status information
        #
        
        startup.initVersionInfo()

        # set start time for restart checking
        cfg['global']['start_time'] = time.time()

        # setup global error handling page
        cfg['global']['error_page.default'] = error.handleError

        # set splunkd connection timeout
        import splunk.rest
        defaultSplunkdConnectionTimeout = 30
        try:
            splunkdConnectionTimeout = int(global_cfg.get('splunkdConnectionTimeout',defaultSplunkdConnectionTimeout))
            if splunkdConnectionTimeout < defaultSplunkdConnectionTimeout:
                splunkdConnectionTimeout = defaultSplunkdConnectionTimeout

            splunk.rest.SPLUNKD_CONNECTION_TIMEOUT = splunkdConnectionTimeout
        except ValueError, e:
            logger.error("Exception while trying to get splunkdConnectionTimeout from web.conf e=%s" % e)
            splunk.rest.SPLUNKD_CONNECTION_TIMEOUT = defaultSplunkdConnectionTimeout
        except TypeError, e:
            logger.error("Exception while trying to get splunkdConnectionTimeout from web.conf e=%s" % e)
            splunk.rest.SPLUNKD_CONNECTION_TIMEOUT = defaultSplunkdConnectionTimeout
        finally:    
            logger.info("splunkdConnectionTimeout=%s" % splunk.rest.SPLUNKD_CONNECTION_TIMEOUT)

        #
        # TODO: refactor me into locale stuff
        #
        cfg['global']['DISPATCH_TIME_FORMAT'] = '%s.%Q'
        # END
        
        
        # Common splunk paths
        cfg['global']['etc_path'] = make_absolute(SPLUNK_ETC_PATH)
        cfg['global']['site_packages_path'] = make_absolute(SPLUNK_SITE_PACKAGES_PATH)
        cfg['global']['mrsparkle_path'] = make_absolute(SPLUNK_MRSPARKLE_PATH)
        
        listen_on_ipv6 = global_cfg.get('listenOnIPv6')
        socket_host = global_cfg.get('server.socket_host')
        if not socket_host:
            if listen_on_ipv6:
                socket_host = global_cfg['server.socket_host'] = '::'
            else:
                socket_host = global_cfg['server.socket_host'] = '0.0.0.0'
            logger.info("server.socket_host defaulting to %s" % socket_host)

        if ':' in socket_host:
            if not listen_on_ipv6:
                logger.warn('server.socket_host was set to IPv6 address "%s", so ignoring listenOnIPv6 value of "%s"' % (socket_host, listen_on_ipv6))
        else:
            if listen_on_ipv6:
                logger.warn('server.socket_host was to to IPv4 address "%s", so ignoring listenOnIPv6 values of "%s"' % (socket_host, listen_on_ipv6))

        if socket_host == '::':
            # Start a second server to listen to the IPV6 socket
            if isinstance(listen_on_ipv6, bool) or listen_on_ipv6.lower() != 'only':
                global_cfg['server.socket_host'] = '0.0.0.0'
                from cherrypy import _cpserver
                from cherrypy import _cpwsgi_server
                server2 = _cpserver.Server()
                server2.httpserver = _cpwsgi_server.CPWSGIServer()
                server2.httpserver.bind_addr = ('::', global_cfg['server.socket_port'])
                server2.socket_host = '::'
                server2.socket_port = global_cfg['server.socket_port']
                for key in ('ssl_private_key', 'ssl_certificate', 'ssl_v3_only', 'ssl_ciphers'):
                    if 'server.'+key in global_cfg:
                        setattr(server2, key, global_cfg['server.'+key])
                        setattr(server2.httpserver, key, global_cfg['server.'+key])
                server2.subscribe()

        if root_name:
            # redirect / to the root endpoint
            cherrypy.tree.mount(RootController(), '/', cfg)

        cherrypy.config.update(cfg)
        if global_cfg.get('enable_profile', False):
            from cherrypy.lib import profiler
            cherrypy.tree.graft(
                profiler.make_app(cherrypy.Application(ctrl, '/' + root_name, cfg), 
                path=global_cfg.get('profile_path', '/tmp/profile')), '/' + root_name
                )
        else:
            cherrypy.tree.mount(ctrl, '/' + root_name, cfg)
        cherrypy.engine.signal_handler.subscribe()

        # this makes Ctrl-C work when running in nodaemon
        if splunk.clilib.cli_common.isWindows:
            from cherrypy.process import win32
            cherrypy.console_control_handler = win32.ConsoleCtrlHandler(cherrypy.engine)
            cherrypy.engine.console_control_handler.subscribe() 

        # log active config
        for k in sorted(cherrypy.config):
            logger.info('CONFIG: %s (%s): %s' % (k, type(cherrypy.config[k]).__name__, cherrypy.config[k]))

        # clean up caches on init
        filechain.clear_cache()
        i18n.init_i18n_cache(flush_files=True)
 
        try:
            configure_django(global_cfg)
        except Exception, e:
            logger.error("DJANGO: There was an error starting:")
            logger.exception(e)
        
        cherrypy.engine.start()


        if blocking:
            # this routine that starts this as a windows service will not want us to block here.
            cherrypy.engine.block()

    
    def configure_django(global_cfg):
        django_cfg = splunk_to_cherry_cfg("web", "framework")

        # Get the splunk root (which may be in shared storage for SHP)
        splunk_root = os.path.abspath(os.path.join(splunk.clilib.bundle_paths.get_shared_etc(), ".."))
        
        # As a starting assumption, Django is not running
        cherrypy.config['django'] = 0
        
        # We only start Django if it has been sufficiently setup
        ENABLE_DJANGO = django_cfg.get("django_enable", False)
        FORCE_ENABLE_DJANGO = django_cfg.get("django_force_enable", False)
        FRAMEWORK_PATH = os.path.join(splunk_root, django_cfg.get("django_path", ""))
        
        if ENABLE_DJANGO:
            logger.info("DJANGO: configuring...")
            
            # Setup python path so that we can import app framework components
            sys.path.append(os.path.join(FRAMEWORK_PATH, "cli"))
            sys.path.append(os.path.join(FRAMEWORK_PATH, "server"))
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
            
            # Try and load an existing config and updating it, or generate
            # a brand new config if none exists
            RCPATH = os.path.join(FRAMEWORK_PATH, ".splunkdjrc_splunkweb")
            if os.path.exists(RCPATH):
                SPLUNKDJ_CONFIG = generate_framework_config(global_cfg, django_cfg, path=RCPATH, generate_secret_key=False)
            else:
                SPLUNKDJ_CONFIG = generate_framework_config(global_cfg, django_cfg, path=RCPATH, generate_secret_key=True)
                
            os.environ['SPLUNKDJ_CONFIG'] = RCPATH
            
            if should_start_django() or FORCE_ENABLE_DJANGO:
                # Start Django stuff
                from splunkdj.management.commands.runwsgiserver import LoggingWSGIHandler
                from splunkdj.management.commands.wsgiserver import mediahandler
                from django.conf import settings
                django = LoggingWSGIHandler()
                
                # Graft it on
                cherrypy.tree.graft(django, '/%s' % SPLUNKDJ_CONFIG.get("mount"))
                
                # Create a media handler for the static files
                staticHandler = mediahandler.MediaHandler(settings.STATIC_ROOT)
            
                # Graft Django static server on
                cherrypy.tree.graft(staticHandler, settings.STATIC_URL)
                
                logger.info("DJANGO: starting, found apps: %s" % list(settings.DISCOVERED_APPS))
                logger.info("DJANGO: mount: /%s -- static mount: %s" % (SPLUNKDJ_CONFIG.get("mount"), settings.STATIC_URL))
                
                # Since Django started, we can note that
                cherrypy.config['django'] = len(settings.DISCOVERED_APPS)
                
                # Add the django mount, but without the root_endpoint
                cherrypy.config['django_mount'] = "/%s" % SPLUNKDJ_CONFIG.get("raw_mount")
            else:
                logger.info("DJANGO: not starting, found no apps")
    
    def should_start_django():
        from django.conf import settings
        return len(settings.DISCOVERED_APPS) > 0
    
    def generate_framework_config(global_cfg, django_cfg, path, generate_secret_key):     
        server_ssl_config = splunk_to_cherry_cfg("server", "sslConfig")
        
        splunk_home = os.environ['SPLUNK_HOME']
        splunkweb_scheme = "https" if normalizeBoolean(global_cfg.get('enableSplunkWebSSL', False)) else "http"
        splunkweb_host = "localhost"
        splunkweb_port = int(global_cfg.get("httpport"))
        splunkweb_mount = global_cfg.get('root_endpoint', FAILSAFE_ROOT_ENDPOINT).strip('/')
        splunkd_scheme = "https" if normalizeBoolean(server_ssl_config.get('enableSplunkdSSL', False)) else "http"
        splunkd_host = splunk.getDefault("host")
        splunkd_port = splunk.getDefault("port")
        x_frame_options_sameorigin = normalizeBoolean(global_cfg.get('x_frame_options_sameorigin', True))
        
        mount = raw_mount = "dj"
        proxy_path = "/en-us/splunkd/__raw"
        if splunkweb_mount:
            mount = "/%s/%s" % (splunkweb_mount, mount)
            proxy_path = "/%s%s" % (splunkweb_mount, proxy_path)
        
        if ":" in splunkd_host:
            splunkd_host = "[%s]" % splunkd_host
        
        import appdo
        return appdo.create_config_file(
            config_file_path           = path,
            generate_secret_key        = generate_secret_key,
            splunk_home                = splunk_home,
            splunkd_scheme             = splunkd_scheme,
            splunkd_host               = splunkd_host,
            splunkd_port               = int(splunkd_port),
            splunkweb_scheme           = splunkweb_scheme,
            splunkweb_host             = splunkweb_host,
            splunkweb_port             = int(splunkweb_port),
            splunkweb_mount            = splunkweb_mount,
            splunkdj_port              = int(splunkweb_port),
            x_frame_options_sameorigin = x_frame_options_sameorigin,
            mount                      = mount,
            raw_mount                  = raw_mount,
            proxy_path                 = proxy_path,
            debug                      = False,
            quickstart                 = False,
            splunkweb_integrated       = True
        )

    if __name__ == '__main__':
        run(blocking=True)


except Exception, e:
    logger.error('Unable to start splunkweb')
    logger.exception(e)
    sys.exit(1)
