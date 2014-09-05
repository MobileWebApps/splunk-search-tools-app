import cherrypy
import xml.sax.saxutils as su
from splunk.appserver.mrsparkle import *
import splunk.entity as en
import logging
import urllib, urllib2
from urlparse import urlsplit, urlunsplit, SplitResult
import splunk.clilib.cli_common as comm

DEFAULT_SERVICES_URL = '/services/pdfserver/renderpdf'

ALERT_ACTIONS_ENTITY = '/configs/conf-alert_actions'

logger = logging.getLogger('splunk.appserver.controllers.report')

class SimpleError(cherrypy.HTTPError):
    def __init__(self, status=500, message=None):
        logger.error("SimpleError status=%s message=%s" % (status, message))
        super(SimpleError, self).__init__(status, message)

    def get_error_page(self, *a, **kw):
        return '>'+self._message


class ReportController(BaseController):
    """/report
    Submits requests to a local or remote PDF server and returns the result
    """

    def build_session(self, username, session_key):
       # create a new session object of the same storage type as currently in use
        active_session = cherrypy.serving.session
        session_args = ('timeout', 'clean_freq', 'storage_path', 'servers')
        args = dict([ (arg_name, getattr(active_session, arg_name)) for arg_name in session_args if hasattr(active_session, arg_name)])
        fake_session = cherrypy.serving.session.__class__(**args)

        fake_session['sessionKey'] = session_key
        # Bypass any SSO checks when Firefox makes it's request as the session is already setup
        fake_session['SSO_DISABLE'] = 1
        # from controllers/account.py
        fake_session['user'] = {
            'name': username,
            'fullname': 'Report User',
            'id': -1
        }
        fake_session.save()
        fake_session.release_lock()
        return fake_session

    def teardown_session(self, session):
        session.delete()

    def get_cert(self):
        """
        Get the server's SSL certificate, if running in SSL mode
        and cache it for future use
        """
        cert = cherrypy.config.get('ssl_certificate_data')
        if not cert:
            cert_fn = cherrypy.config.get('server.ssl_certificate')
            logger.warn('CERT = %s' % cert_fn)
            if cert_fn:
                cert = cherrypy.config['ssl_certificate_data'] =  file(cert_fn).read()
            else:
                cert = cherrypy.config['ssl_certificate_data'] = ''
        return cert


    @expose_page(handle_api=True)
    @set_cache_level('etag')
    def is_enabled(self, **kw):
        """
        Determine whether the PDF server is installed and enabled for the current user
        """
        try:
            installed = False
            settings = en.getEntity(ALERT_ACTIONS_ENTITY, 'email')
            serverURL = settings.get('reportServerURL') or ''
            if serverURL.strip() == '':
                # if reportServerURL is blank then this system should actually have the app installed; check for that.
                # will raise a ResourceNotFound exception if not installed
                if comm.isWindows:
                    # will raise a ResourceNotFound exception if our PDF driver is not installed
                    en.getEntity('/pdfserver', 'renderpdf')
                else:
                    en.getEntity('/apps/local', 'pdfserver')
                installed = True

            # next check that it's actually turned on in email settings;
            # on Windows, ther server is always enabled
            status = 'enabled' if comm.isWindows or splunk.util.normalizeBoolean(settings.get('reportServerEnabled')) else 'disabled'
        except splunk.ResourceNotFound:
            status = 'notinstalled'
        except splunk.AuthorizationFailed:
            status = 'denied'
        except splunk.LicenseRestriction:
            status = 'denied'
        response = {
            'installed': installed,
            'status': status
        }
        return self.render_json(response)


    @expose_page(must_login=False, verify_sso=False, methods=['POST'], verify_session=False)
    def index(self, **kw):
        return self.requestPDF(**kw)

    # requestPDF is broken out into a standalone method so that it can be invoked as a subrequest
    # from the view controller
    def requestPDF(self, **kw):
        """
        Expects a valid splunk session key to be passed in along with the url to be rendered to PDF
        Complete parameter list:
        session_key (required)
        request_path (required)
        paperSize - 'a4', 'letter', etc or dimensions in mm '200x400' - default 'letter'
        orientation - 'portrait' or 'landscape' - default 'portrait'
        title - Title of report - default 'Splunk Report'
        override_disposition
        owner
        """

        request_path = kw.get('request_path')
        if not request_path: 
            raise SimpleError(400, "Invalid request_path supplied")

        print_session_key = kw.get('session_key')
        if not print_session_key:
            if cherrypy.config.get('debug_report_server'):
                logger.warn('Using debug user for report server')
                print_session_key = splunk.auth.getSessionKey('admin', 'changeme', hostPath=self.splunkd_urlhost)
            else:
                raise SimpleError(400, "Invalid session key supplied")


        settings = en.getEntity(ALERT_ACTIONS_ENTITY, 'email', namespace='system', sessionKey=print_session_key, owner='nobody')

        enabled = splunk.util.normalizeBoolean(settings.get('reportServerEnabled'))
        if not enabled:
            raise SimpleError(400, 'PDF server is not enabled')

        report_server_url = settings.get('reportServerURL')
        if isinstance(report_server_url, basestring):
            report_server_url = report_server_url.strip()
            url = urlsplit(report_server_url)
            if url.netloc and len(url.path)<2:
                # user has specified the protocol://host:port only
                url = url._asdict()
                url['path'] = DEFAULT_SERVICES_URL
                report_server_url = urlunsplit(SplitResult(**url))
        elif report_server_url is None:
            report_server_url = DEFAULT_SERVICES_URL
        else:
            raise SimpleError(500, "reportServerURL is invalid")
        if not report_server_url:
            report_server_url = DEFAULT_SERVICES_URL

        papersize = kw.get('papersize')
        if not papersize:
            papersize = settings.get('reportPaperSize', 'letter')

        orientation = kw.get('orientation')
        if not orientation:
            orientation = settings.get('reportPaperOrientation', 'portrait')

        title = kw.get('title')
        if not title:
            title = settings.get('reportTitle', _('Splunk Report'))

        owner = kw.get('owner', 'nobody')
        print_session = self.build_session(owner, print_session_key)

        try:
            data = {
                'session': print_session.id,
                'target': request_path,
                'papersize': papersize,
                'orientation': orientation,
                'title': title,
                'footer_right': _('Generated by Splunk at %(time)s') % dict(time='&D'),
                'mode': 'splunk'
            }

            # see if splunkweb is running in SSL mode; if so pass the certificate to the pdf server
            cert = self.get_cert()
            if cert:
                data['cert'] = cert

            try:
                logger.info("Appserver dispatching report request to '%s'" % report_server_url)
                server_response, server_content = splunk.rest.simpleRequest(report_server_url, postargs=data, rawResult=True, timeout=1800)
            except Exception, e:
                logger.error("Appserver failed to dispatch report request to %s: %s" % (report_server_url, e))
                raise SimpleError(500, "Appserver failed to dispatch report request to %s: %s" % (report_server_url, e))

            if server_response.status==404:
                logger.error("Appserver got a 404 response while contacting the PDF server at %s - Check that the PDF Server app is installed and that reportServerURL is correct" % report_server_url)
                raise SimpleError(500, "Appserver got a 404 response while contacting the PDF server at %s - Check that the PDF Server app is installed and that reportServerURL is correct" % report_server_url)
            elif server_response.status!=200:
                if server_content and server_content[0] == '>':
                    logger.error("Appserver received error from PDF server at %s: %s" % (report_server_url, server_content[1:]))
                    raise SimpleError(server_response.status, "PDF server at %s returned error: %s" % (report_server_url, server_content[1:]))
                logger.error("Appserver failed to dispatch report request to %s: %s - %s" % (report_server_url, server_response.status, server_response.reason))
                raise SimpleError(500, "Appserver failed to dispatch report request to %s: %s %s" % (report_server_url, server_response.status, server_response.reason))
            
            # relay the response through to the requester
            cherrypy.response.headers['content-type'] = server_response['content-type']
            cherrypy.response.headers['content-length'] = server_response['content-length']
            if kw.get('override_disposition'):
                cherrypy.response.headers['content-disposition'] = kw['override_disposition']
            elif 'content-disposition' in server_response:
                cherrypy.response.headers['content-disposition'] = server_response['content-disposition']
            cherrypy.response.body = server_content
            return cherrypy.response.body
        
        finally:
            logger.warn("Tearing down session %s" % print_session.id)
            self.teardown_session(print_session)


