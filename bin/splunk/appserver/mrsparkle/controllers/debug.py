import sys
import cherrypy
import splunk
from splunk.appserver.mrsparkle import *
from splunk.appserver.mrsparkle.controllers.config import ConfigController
from splunk.appserver.mrsparkle.lib.module import *
import splunk.appserver.mrsparkle.lib.util as util
import splunk.appserver.mrsparkle.lib.cached as cached
from splunk.appserver.mrsparkle.lib import decorators, filechain
import logging
import splunk.util
import os, json, time, urllib, socket, urlparse
from urlparse import urlsplit, urlunsplit, SplitResult
import httplib2
import splunk.rest
import splunk.entity as en
import splunk.search as se
import splunk.auth as au
import splunk.clilib.cli_common as comm
import __main__

import view

logger = logging.getLogger('splunk.appserver.controllers.debug')

COVERAGE_URI_PATH = 'app/testing/jscoverage'

class DebugController(BaseController):
    """/debug"""

    #@route('/:p=status')
    # @expose_page(methods='GET')
    def status(self, **args):
        '''
        Provides a debug output page for appserver config
        '''
        hasReadPerms = self._hasReadPerms()

        # get overview items
        general = splunk.util.OrderedDict()
        general['Appserver boot path'] = getattr(__main__,'__file__', '<N/A>')
        general['Splunkd URI'] = splunk.mergeHostPath()
        general['Debug Mode'] = __debug__

        # get various dicts
        configController = ConfigController()
        uiConfig = configController.index(asDict=True)

        mm = moduleMapper
        moduleMap = mm.getInstalledModules()

        uiPanels = splunk.util.OrderedDict()
        uiPanels['config'] = uiConfig
        uiPanels['views'] = en.getEntities(view.VIEW_ENTITY_CLASS, namespace=splunk.getDefault('namespace'))
        uiPanels['modules'] = moduleMap
        uiPanels['cherrypy'] = cherrypy.config
        uiPanels['request'] = args
        uiPanels['wsgi'] = cherrypy.request.wsgi_environ

        splunkdPanels = splunk.util.OrderedDict()

        #code to display splunkd debug information as well
        try:
            serverResponse, serverContent = splunk.rest.simpleRequest('/services/debug/status', sessionKey=cherrypy.session['sessionKey'])
            atomFeed = splunk.rest.format.parseFeedDocument(serverContent)
            atomFeed_prim = atomFeed.toPrimitive()
            general['Splunkd time'] = splunk.util.getISOTime(atomFeed.updated)
            general['Splunkd home'] = atomFeed_prim.get('SPLUNK_HOME', '&lt;unknown&gt;')

            for key in atomFeed_prim:
                splunkdPanels[key] = atomFeed_prim[key]

        except splunk.AuthenticationFailed, e:
            splunkdPanels['errors'] = 'The appserver is not authenticated with splunkd; retry login'

        except splunk.SplunkdConnectionException, e:
            splunkdPanels['errors'] = 'The appserver could not connect to the splunkd instance at: %s' % splunk.mergeHostPath()

        except Exception, e:
            splunkdPanels['errors'] = 'Unhandled exception: %s' % str(e)


        cherrypy.response.headers['content-type'] = MIME_HTML

        return self.render_template('debug/status.html', {
            'uiPanels': uiPanels,
            'splunkdPanels': splunkdPanels,
            'appserverTime': splunk.util.getISOTime(),
            'general': general,
            'hasReadPerms': hasReadPerms
        })


    def _hasReadPerms(self):
        '''
        Use services/server/settings as a proxy for read permissions.
        '''

        # NOTE:Due SPL-21113 BETA: unify ACL actions to read/write we cannot use the settings endpoint defer to user admin for now.
        return True if 'admin' == au.getCurrentUser()['name'] else False

        entity = None
        try:
            entity = en.getEntity('/server/', 'settings', namespace=splunk.getDefault('namespace'))
        except Exception, e:
            return False
        if not entity['eai:acl']:
            return False
        if not entity['eai:acl']['perms']:
            return False
        if au.getCurrentUser()['name'] in entity['eai:acl']['perms'].get('read', []):
            return True
        else:
            return False

    def find_unittests(self, path, ext='.html', staticBase=True):
        relativePath = path.strip('/\\')
        extension = ext

        if staticBase:
            testFileDir = os.path.join(cherrypy.config['staticdir'], relativePath)
        else:
            testFileDir = os.path.join(self.get_qunit_base_path(), relativePath)
        logger.debug('Fetching HTML test files from: %s' % testFileDir)

        output = []
        for root, dirs, files in os.walk(testFileDir):
            for f in files:
                if f.endswith(extension):
                    base = root.replace(testFileDir, '')
                    if len(base) > 0:
                        # strip the leading slash and add the file name
                        output.append(base[1:] + '/' + f)
                    else:
                        output.append(f)
        return output

    def get_qunit_base_path(self):
        return util.make_absolute(cherrypy.config.get('templates', 'share/splunk/search_mrsparkle/templates'))

    @route('/:p=jsunits')
    def unittests(self, **kwargs):
        '''
        Returns a JSON array of all the HTML jsunit tests in mrsparkle

        Ex:

        [
            ["all", "/splunk/static/@40691/testing/tests/all.html"],
            ["ascii_timeline", "/splunk/static/@40691/testing/tests/ascii_timeline.html"],
            ["job", "/splunk/static/@40691/testing/tests/job.html"]
        ]
        '''
        path = '/testing/tests'
        tests = self.find_unittests(path)
        output = [(test[0:-len('.html')], self.make_url(['static', 'testing', 'tests', test])) for test in tests]
        return self.render_json(output, set_mime='text/plain')


    @route('/:p=qunit_tests')
    def qunit_unittests(self, **kwargs):
        tests = self.find_unittests('/testing/qunit', staticBase=False)
        test_paths = [(test[0:-len('.html')], self.make_url(['debug', 'qunit', test[0:-len('.html')]])) for test in tests]
        return self.render_json(test_paths)

    @route('/:p=qunit/*path')
    def qunit(self, path, **kwargs):
        '''
        Serves up qunit tests, path is relative to the /templates/testing/qunit directory.
        If path points to a directory, will run all tests in that directory (and subdirectories).
        Set path to 'test_all' to run all tests.
        '''

        referer = cherrypy.request.headers.get('Referer', '')
        if 'instrument' in kwargs:
            self.instrument = splunk.util.normalizeBoolean(kwargs['instrument'])
        elif COVERAGE_URI_PATH in referer:
            self.instrument = True
        else:
            self.instrument = False

        template_info = {
            'instrument': self.instrument,
            'coverage_path': COVERAGE_URI_PATH,
            'host': cherrypy.request.headers.get('Host', ''),
            'headless': False
        }

        if path == 'test_all':
            tests = self.find_unittests('/testing/qunit', staticBase=False)
            template_info['tests'] = tests
            template_info['base_url'] = self.make_url(['debug', 'qunit'])
            return self.render_template('qunit/test_all.html', template_info)
        else:
            path_with_qunit_dir = 'testing/qunit/%s' % path
            full_path = os.path.join(self.get_qunit_base_path(), path_with_qunit_dir)
            if os.path.isdir(full_path):
                tests = self.find_unittests(path_with_qunit_dir, staticBase=False)
                template_info['tests'] = tests
                template_info['base_url'] = self.make_url(['debug', 'qunit', path])
                return self.render_template('qunit/test_all.html', template_info)
            else:
                template_info['test_url'] = self.make_url(['debug', 'qunit', path])
                if path.endswith('.html'):
                    return self.render_template('testing/qunit/%s' % path, template_info)
                else:
                    return self.render_template('testing/qunit/%s.html' % path, template_info)

    def make_url(self, *a, **kw):
        if hasattr(self, 'instrument') and self.instrument:
            if str(a).find('contrib') < 0 and str(a).find('i18n') < 0 and str(a).find('static/js') >= 0:
                swap_list = []
                for i in a:
                    i = str(i).replace('static/js', 'static/app/testing/js_instrumented')
                    swap_list.append(i)

                a = tuple(swap_list)
        return super(DebugController, self).make_url(*a, **kw)

    @route('/:p=reset')
    def reset(self, **kwargs):
        '''
        Resets the user space to a clean state; usually used for testingm
        '''
        has_perms = True if 'admin'==au.getCurrentUser()['name'] else False
        jobs_cancelled = []
        if has_perms and cherrypy.request.method=='POST':
            jobs = se.listJobs()
            for job in jobs:
                try:
                    j = se.getJob(job['sid'])
                    j.cancel()
                    jobs_cancelled.append(job['sid'])
                except splunk.ResourceNotFound:
                    continue
        return self.render_template('debug/reset.html', {
            'has_perms': has_perms,
            'method': cherrypy.request.method,
            'jobs_cancelled': jobs_cancelled
        })

    @expose_page(must_login=False, methods=['GET', 'POST'])
    def echo(self, **kw):
        '''echos incoming params'''

        output = {
            'headers': cherrypy.request.headers,
            'params': cherrypy.request.params
        }

        return self.render_template('debug/echo.html', output)


    @expose_page()
    def refresh(self, entity=None, **kwargs):
        '''
        Forces a refresh on splunkd resources

        This method calls a splunkd refresh on all registered EAI handlers that
        advertise a reload function.  Alternate entities can be specified by appending
        them via URI parameters.  For example,

            http://localhost:8000/debug/refresh?entity=admin/conf-times&entity=data/ui/manager

        will request a refresh on only 'admin/conf-times' and 'data/ui/manager'.

        1) not all splunkd endpoints support refreshing.
        2) auth-services is excluded from the default set, as refreshing that system will
           logout the current user; use the 'entity' param to force it
        '''

        # get auto-list of refreshable EAI endpoints
        allEndpoints = en.getEntities('admin', namespace="search")
        eligibleEndpoints = {}

        for name in allEndpoints:
            for link in allEndpoints[name].links:
                if link[0] == '_reload':
                    logger.debug('FOUND reload for %s' % name)
                    eligibleEndpoints[name] = allEndpoints[name]
                    break

        if isinstance(entity, list):
            entityPaths = entity
        elif isinstance(entity, basestring):
            entityPaths = [entity]
        else:
            # seed manual endpoints
            entityPaths = [
                'admin/conf-times',
                'data/ui/manager',
                'data/ui/nav',
                'data/ui/views'
            ]

            # add capable endpoints
            for name in sorted(eligibleEndpoints.keys()):
                if name in ['auth-services']: # refreshing auth causes logout
                    continue
                if sys.platform == 'win32' and name == 'fifo':
                    # splunkd never loads FIFO on windows, but advertises it anyway
                    continue
                entityPaths.append('%s/%s' % (allEndpoints[name].path, allEndpoints[name].name))


        cherrypy.response.headers['content-type'] = MIME_TEXT

        output = ['Entity refresh control page']
        output.append('=' * len(output[0]))
        output.append("'''")
        output.append(self.refresh.__doc__.strip())
        output.append("'''")
        output.append('')

        # call refresh on each
        for path in entityPaths:
            try:
                en.refreshEntities(path, namespace='search')
                output.append(('Refreshing %s' % path).ljust(40, ' ') + 'OK')
            except Exception, e:
                logger.exception(e)
                msg = e
                if hasattr(e, 'extendedMessages') and e.extendedMessages:
                    msg = e.extendedMessages[0]['text']
                output.append(('Refreshing %s' % path).ljust(43, ' ') + e.__class__.__name__ + ' ' + unicode(msg))

        output.append('DONE')
        return '\n'.join(output)


    @expose_page(must_login=False, verify_sso=False)
    def sso(self):
        import socket

        enabled = _("No")
        proxy_to_cherrypy = _('SSO is not enabled.')
        if util.in_sso_mode():
            enabled = _("Yes")
            if cherrypy.request.remote.ip not in splunk.util.stringToFieldList(cherrypy.config.get('trustedIP')):
                proxy_to_cherrypy = _("No. SSO will not be used to authenticate this request.")
            else:
                proxy_to_cherrypy = _("Yes. SSO will be used to authenticate this request.")

        remote_user_header_name = cherrypy.request.config.get('remoteUser') or decorators.DEFAULT_REMOTE_USER_HEADER

        remote_user = cherrypy.request.headers.get(remote_user_header_name)
        if remote_user == None:
            remote_user = _("Not set. SSO may not be enabled or you may not be accessing Splunk via your proxy server.")

        server_info = splunk.entity.getEntity('/server', 'info', namespace=None, owner='anon')
        sso_mode = cherrypy.request.config.get(decorators.SPLUNKWEB_SSO_MODE_CFG)

        output = {
            'host_name': socket.gethostname(),
            'host_ip': socket.gethostbyname(socket.gethostname()),
            'port': cherrypy.config.get('httpport'),
            'sso_enabled': enabled,
            'splunkweb_trusted_ip': cherrypy.config.get('trustedIP') or _('Not set. To enable try configuring the trustedIP setting in web.conf.'),
            'splunkd_trusted_ip': cherrypy.config.get('splunkdTrustedIP') or _('Not set. To enable try configuring the trustedIP setting in server.conf.'),
            'splunkweb_trusted_ip_matches': proxy_to_cherrypy,
            'splunkweb_remote_ip': cherrypy.request.remote.ip,
            'remote_user': remote_user,
            'remote_user_header_name': remote_user_header_name,
            'headers': cherrypy.request.headers,
            'sso_mode': sso_mode
        }

        return self.render_template('debug/sso.html', output)


    @expose_page()
    def pdf(self):
        '''
        Provides debug services for PDF server
        '''

        status = {
            'pdfIsInstalled': False,
            'pdfIsEnabled': False,
            'smtpIsSet': False,
            'configuration': {}
        }

        # check that PDF app is installed
        try:
            if comm.isWindows:
                en.getEntity('/pdfserver', 'renderpdf')
            else:
                en.getEntity('admin/localapps', 'pdfserver', namespace='search')
            status['pdfIsInstalled'] = True
        except splunk.ResourceNotFound:
            pass
        except Exception, e:
            logger.exception(e)
            status['pdfIsInstalled'] = e

        # check for enabled, SMTP, and PDF config
        try:
            alertSettings = en.getEntity('configs/conf-alert_actions', 'email', namespace='search')
            status['pdfIsEnabled'] = splunk.util.normalizeBoolean(alertSettings.get('reportServerEnabled'))
            status['smtpIsSet'] = True if alertSettings.get('mailserver') else False
            for k in alertSettings:
                if k.startswith('report'):
                    status['configuration'][k] = alertSettings[k]
        except Exception, e:
            logger.exception(e)
            status['pdfIsInstalled'] = e

        return self.render_template('debug/pdf.html', {'status': status})


    @expose_page()
    def pdf_echo(self):
        '''
        Adjunct endpoint that serves a known page for the PDF server to capture
        '''
        cherrypy.response.headers['content-type'] = MIME_HTML
        return '''<html>
            <head><title>PDF Test HTML title</title></head>
            <body>You are seeing a PDF generated for an appserver page on %s</body>
        </html>''' % time.ctime()


    @expose_page()
    def pdf_echo_loopback(self):
        '''
        Adjunct endpoint used with above PDF test echo page that proxies the
        generated PDF back to the test page
        '''

        # set default PDF server URI
        pdfServerUri = '%s://%s/services/pdfserver/renderpdf' % (splunk.getDefault('protocol'), cherrypy.config.get('mgmtHostPort'))

        # get alternate PDF server URI; values seem to be varied so we normalize
        alertSettings = en.getEntity('configs/conf-alert_actions', 'email', namespace='search')
        if alertSettings.get('reportServerURL') and alertSettings['reportServerURL'].strip():
            pdfServerUri = alertSettings['reportServerURL'].strip()
            url = urlsplit(pdfServerUri)
            if len(url.path)<2:
                url = url._asdict()
                url['path'] = '/services/pdfserver/renderpdf'
                pdfServerUri = urlunsplit(SplitResult(**url))

        # determine the external address that is most likely accessible
        urlparts = urlparse.urlparse(pdfServerUri)

        ai = socket.getaddrinfo(urlparts.hostname, int(urlparts.port or 80), socket.AF_UNSPEC, socket.SOCK_STREAM, 0, socket.AI_PASSIVE)[0]
        af, socktype, proto, canonname, hostport = ai

        appserverHost = alertSettings.get('hostname') and alertSettings['hostname'].strip()
        if appserverHost:
            logger.info('using configured appserver hostname "%s"' % appserverHost)
        else:
            s = socket.socket(af, socktype, proto)
            s.connect(hostport)
            sockname = s.getsockname()
            logger.info('most promising interface looks like %s' % sockname[0])
            appserverHost = sockname[0]

        appserverProtocol = 'https' if splunk.util.normalizeBoolean(cherrypy.config.get('enableSplunkWebSSL', False)) else 'http'

        # create a fake sso-bypass session utilizing the user's current sessionKey
        active_session = cherrypy.serving.session
        session_args = ('timeout', 'clean_freq', 'storage_path', 'servers')
        args = dict([ (arg_name, getattr(active_session, arg_name)) for arg_name in session_args if hasattr(active_session, arg_name)])
        fake_session = cherrypy.serving.session.__class__(**args)
        fake_session['sessionKey'] = cherrypy.session['sessionKey']
        fake_session['SSO_DISABLE'] = 1
        fake_session.save()
        fake_session.release_lock()

        cherrypy.session.release_lock()

        # set GET args
        args = {
            'target': '%s://%s:%s%s/debug/pdf_echo' % (
                appserverProtocol,
                appserverHost if af == socket.AF_INET else '[%s]' % appserverHost,
                cherrypy.config['httpport'],
                cherrypy.request.script_name
                ),
            'mode': 'default',
            'session': fake_session.id
        }

        # fetch the SSL certificate, if any
        cert = cherrypy.request.app.root.report.get_cert()
        if cert:
            args['cert'] = cert

        logger.info('Testing PDF server=%s on URI=%s' % (pdfServerUri, args['target']))

        # make a request to the registered PDF server for the echo page
        timeout = 20
        h = httplib2.Http(timeout=timeout, disable_ssl_certificate_validation=True)
        start = time.time()
        try:
            serverResponse, serverContent = h.request(pdfServerUri, method='POST', body=urllib.urlencode(args))
        except:
            if time.time() - start > (timeout-1):
                cherrypy.response.headers['content-type'] = 'text/plain'
                return "Timed out while waiting for a response"
            raise

        cherrypy.response.headers['content-type'] = 'application/pdf'
        return serverContent



    @expose_page()
    def clear_cache(self, **unused):
        if cherrypy.request.method == 'POST':
            filechain.clear_cache()
            return 'Cache clear requested.'

        return '''
            <html><form method="POST">
            <input type="hidden" name="splunk_form_key" value="%s"/>
            <button type="submit">Clear minification cache</button>
            </form></html>
        ''' % cherrypy.session.get('csrf_form_key')


    @expose_page()
    def memotest(self):

        logger.debug("TEST: first call to getEntities")
        cached.getEntities('saved/searches', 'search')
        logger.debug("TEST: second call to getEntities should be cached")
        cached.getEntities('saved/searches', 'search')
        logger.debug("TEST: third call to getEntities should be cached")
        cached.getEntities('saved/searches', search="search")
        logger.debug("TEST: fourth call to getEntities should be cached")
        cached.getEntities('saved/searches', search="search")
        logger.debug("TEST: fourth call to getEntities should be cached")
        cached.getEntities('saved/searches', search={1:2,3:4,5:6})
        logger.debug("TEST: fourth call to getEntities should be cached")
        cached.getEntities('saved/searches', search={1:2,3:4,5:6})
