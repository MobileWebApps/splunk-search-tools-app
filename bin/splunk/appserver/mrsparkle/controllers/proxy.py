import cherrypy
import xml.sax.saxutils as su
from splunk.appserver.mrsparkle import *
from splunk.appserver.mrsparkle.lib.util import make_url
import logging
import splunk.rest, splunk.rest.format
import json
import re
import urllib

logger = logging.getLogger('splunk.appserver.controllers.proxy')
#logger.setLevel(logging.DEBUG)

PDFGEN_RENDER_TIMEOUT_IN_SECONDS = 3600 # same as cherrypy.tools.sessions.timeout
                                        # since this module is loaded before settings are
                                        # fully loaded, we can't use web.conf value here

# GUIDELINES FOR ADDING TO THE PROXY WHITELIST:
# - keep the list in alphabetical order by endpoint
# - there is no need to include the leading '__raw', 'services', or 'servicesNS'

_PROXY_WHITE_LIST = [{'endpoint': 'admin/alerts', 'methods': ['GET', 'DELETE']},
                     {'endpoint': 'admin/alerts/[^/]*', 'methods': ['GET', 'DELETE']},
                     {'endpoint': 'admin/conf-reports', 'methods': ['POST', 'GET', 'DELETE']},
                     {'endpoint': 'admin/conf-impersonation', 'methods': ['POST', 'GET']},
                     {'endpoint': 'admin/conf-impersonation/[^/]*', 'methods': ['POST', 'GET', 'DELETE']},
                     {'endpoint': 'admin/summarization', 'methods': ['POST', 'GET', 'DELETE']},
                     {'endpoint': 'admin/summarization/[^/]*', 'methods': ['GET', 'POST', 'DELETE']},
                     {'endpoint': 'admin/summarization/[^/]*/details', 'methods': ['GET']},
                     {'endpoint': 'admin/users', 'methods': ['GET', 'DELETE']},
                     {'endpoint': 'admin/users/[^/]*', 'methods': ['GET', 'DELETE']},
                     {'endpoint': 'alerts/fired_alerts', 'methods': ['GET']},
                     {'endpoint': 'alerts/fired_alerts/[^/]*', 'methods': ['GET', 'DELETE']},
                     {'endpoint': 'apps/appinstall', 'methods': ['POST']},
                     {'endpoint': 'apps/apptemplates', 'methods': ['GET']},
                     {'endpoint': 'apps/apptemplates/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'apps/local', 'methods': ['POST', 'GET']},
                     {'endpoint': 'apps/local/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'apps/local/[^/]*/package', 'methods': ['GET']},
                     {'endpoint': 'apps/local/[^/]*/setup', 'methods': ['GET']},
                     {'endpoint': 'apps/local/[^/]*/update', 'methods': ['GET']},
                     {'endpoint': 'auth/login', 'methods': ['POST'], 'skipCSRFProtection': True},
                     {'endpoint': 'authentication/auth-tokens', 'methods': ['POST', 'GET']},
                     {'endpoint': 'authentication/current-context', 'methods': ['GET']},
                     {'endpoint': 'authentication/current-context/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'authentication/httpauth-tokens', 'methods': ['GET']},
                     {'endpoint': 'authentication/httpauth-tokens/[^/]*', 'methods': ['GET', 'DELETE']},
                     {'endpoint': 'authentication/users', 'methods': ['POST', 'GET']},
                     {'endpoint': 'authentication/users/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'authorization/capabilities', 'methods': ['GET']},
                     {'endpoint': 'authorization/capabilities/[^/]*/', 'methods': ['GET']},
                     {'endpoint': 'authorization/roles', 'methods': ['POST', 'GET']},
                     {'endpoint': 'authorization/roles/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'cluster/config', 'methods': ['GET']},
                     {'endpoint': 'cluster/config/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'cluster/master/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'cluster/master/[^/]*/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'cluster/master/control/default/apply', 'methods': ['GET','POST']},
                     {'endpoint': 'cluster/slave/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'cluster/slave/info/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'cluster/searchhead/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'cluster/searchhead/generation/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'cluster/searchhead/searchheadconfig/[^/]*', 'methods': ['GET', 'POST', 'DELETE']},
                     {'endpoint': 'configs/conf-[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'configs/conf-[^/]*/[^/]*', 'methods': ['GET', 'POST', 'DELETE']},
                     {'endpoint': 'configs/conf-[^/]*/[^/]*/acl', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/commands', 'methods': ['GET']},
                     {'endpoint': 'data/commands/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'data/indexes', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/indexes/[^/]*', 'methods': ['GET', 'POST', 'DELETE']},
                     {'endpoint': 'data/indexes/[^/]*/disable', 'methods': ['POST']},
                     {'endpoint': 'data/indexes/[^/]*/enable', 'methods': ['POST']},
                     {'endpoint': 'data/inputs/ad', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/ad/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/inputs/monitor', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/monitor/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/inputs/monitor/[^/]*/members', 'methods': ['GET']},
                     {'endpoint': 'data/inputs/oneshot', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/oneshot/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'data/inputs/registry', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/registry/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/inputs/script', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/script/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/inputs/script/restart', 'methods': ['POST']},
                     {'endpoint': 'data/inputs/tcp/cooked', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/tcp/cooked/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/inputs/tcp/cooked/[^/]*/connections', 'methods': ['GET']},
                     {'endpoint': 'data/inputs/tcp/raw', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/tcp/raw/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/inputs/tcp/raw/[^/]*/connections', 'methods': ['GET']},
                     {'endpoint': 'data/inputs/tcp/ssl', 'methods': ['GET']},
                     {'endpoint': 'data/inputs/tcp/ssl/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/inputs/udp', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/udp/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/inputs/udp/[^/]*/connections', 'methods': ['GET']},
                     {'endpoint': 'data/inputs/win-event-log-collections', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/win-event-log-collections/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/inputs/win-perfmon', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/win-perfmon/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/inputs/win-wmi-collections', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/inputs/win-wmi-collections/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/lookup-table-files', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/lookup-table-files/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/outputs/tcp/default', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/outputs/tcp/default/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/outputs/tcp/group', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/outputs/tcp/group/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/outputs/tcp/server', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/outputs/tcp/server/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/outputs/tcp/server/[^/]*/allconnections', 'methods': ['GET']},
                     {'endpoint': 'data/outputs/tcp/syslog', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/outputs/tcp/syslog/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/props/extractions', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/props/extractions/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/props/fieldaliases', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/props/fieldaliases/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/props/lookups', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/props/lookups/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/props/sourcetype-rename', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/props/sourcetype-rename/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/transforms/extractions', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/transforms/extractions/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/transforms/lookups', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/transforms/lookups/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'data/ui/manager', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/ui/manager/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/ui/nav', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/ui/nav/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/ui/prefs', 'methods': ['POST', 'GET']},
                     {'endpoint': 'data/ui/prefs/[^/]*', 'methods': ['POST', 'GET', 'DELETE']},
                     {'endpoint': 'data/ui/times', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/ui/views', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/ui/views/[^/]*', 'methods': ['GET', 'POST', 'DELETE']},
                     {'endpoint': 'data/ui/views/[^/]*/acl', 'methods': ['POST']},
                     {'endpoint': 'data/ui/viewstates', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/ui/viewstates/[^/]*', 'methods': ['GET', 'POST', 'DELETE']},       
                     {'endpoint': 'data/user-prefs', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/user-prefs/[^/]*', 'methods': ['GET', 'POST', 'PUT', 'DELETE']},
                     {'endpoint': 'data/ui/workflow-actions', 'methods': ['GET', 'POST']},
                     {'endpoint': 'data/ui/workflow-actions/[^/]*', 'methods': ['GET', 'POST', 'DELETE']},
                     {'endpoint': 'data/ui/workflow-actions/[^/]*/acl', 'methods': ['POST']}, 
                     {'endpoint': 'data/vix-providers', 'methods': ['GET','POST']}, 
                     {'endpoint': 'data/vix-providers/[^/]*', 'methods': ['GET','POST','DELETE']}, 
                     {'endpoint': 'data/vix-indexes', 'methods': ['GET','POST']}, 
                     {'endpoint': 'data/vix-indexes/[^/]*', 'methods': ['GET','POST','DELETE']},
                     {'endpoint': 'data/vix-indexes/[^/]*/[^/]*', 'methods': ['GET','POST']}, 
                     
                     {'endpoint': 'datamodel/model', 'methods': ['GET', 'POST']},
                     {'endpoint': 'datamodel/model/[^/]*', 'methods': ['GET', 'POST', 'DELETE']},
                     {'endpoint': 'datamodel/model/[^/]*/[^/]*', 'methods': ['POST']},
                     {'endpoint': 'datamodel/model/[^/]*/desc', 'methods': ['GET']},
                     {'endpoint': 'datamodel/pivot/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'data/models/[^/]*/download', 'methods': ['GET']},

                     {'endpoint': 'deployment/server/applications', 'methods': ['POST', 'GET', 'DELETE']},
                     {'endpoint': 'deployment/server/applications/.*', 'methods': ['POST', 'GET', 'DELETE']},
                     {'endpoint': 'deployment/server/clients', 'methods': ['POST', 'GET']},
                     {'endpoint': 'deployment/server/clients/countClients_by_machineType/.* ', 'methods': ['GET']},
                     {'endpoint': 'deployment/server/clients/.*', 'methods': ['POST', 'GET', 'DELETE']},
                     {'endpoint': 'deployment/server/config', 'methods': ['POST', 'GET']},
                     {'endpoint': 'deployment/server/config/.*', 'methods': ['POST', 'GET']},
                     {'endpoint': 'deployment/server/serverclasses', 'methods': ['POST', 'GET']},
                     {'endpoint': 'deployment/server/serverclasses/.*', 'methods': ['POST', 'GET', 'DELETE']},
                     {'endpoint': 'directory', 'methods': ['GET']},
                     {'endpoint': 'directory/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'indexing/preview', 'methods': ['GET', 'POST']},
                     {'endpoint': 'indexing/preview/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'licenser/groups', 'methods': ['GET']},
                     {'endpoint': 'licenser/groups/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'licenser/licenses', 'methods': ['POST', 'GET']},
                     {'endpoint': 'licenser/licenses/[^/]*', 'methods': ['GET', 'DELETE']},
                     {'endpoint': 'licenser/messages', 'methods': ['GET']},
                     {'endpoint': 'licenser/messages/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'licenser/pools', 'methods': ['POST', 'GET']},
                     {'endpoint': 'licenser/pools/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'licenser/slaves', 'methods': ['GET']},
                     {'endpoint': 'licenser/slaves/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'licenser/stacks', 'methods': ['GET']},
                     {'endpoint': 'licenser/stacks/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'mbtiles/splunk-tiles/[^/]*/[^/]*/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'messages', 'methods': ['POST', 'GET']},
                     {'endpoint': 'messages/[^/]*', 'methods': ['GET', 'DELETE']},
                     {'endpoint': 'pdfgen/is_available', 'methods': ['GET']},
                     {'endpoint': 'pdfgen/render', 'methods': ['GET', 'POST'], 'timeout': 3600},
                     {'endpoint': 'properties', 'methods': ['GET', 'POST']},
                     {'endpoint': 'properties/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'properties/[^/]*/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'properties/[^/]*/[^/]*/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'receivers/simple', 'methods': ['POST']},
                     {'endpoint': 'receivers/stream', 'methods': ['POST']},
                     {'endpoint': 'saved/eventtypes', 'methods': ['POST', 'GET']},
                     {'endpoint': 'saved/eventtypes/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'saved/fvtags', 'methods': ['GET', 'POST']},
                     {'endpoint': 'saved/fvtags/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'saved/searches', 'methods': ['POST', 'GET']},
                     {'endpoint': 'saved/searches/[^/]*', 'methods': ['GET', 'DELETE', 'POST'], 'oidEnabled': True},
                     {'endpoint': 'saved/searches/[^/]*/acknowledge', 'methods': ['POST']},
                     {'endpoint': 'saved/searches/[^/]*/acl', 'methods': ['POST']},
                     {'endpoint': 'saved/searches/[^/]*/dispatch', 'methods': ['POST']},
                     {'endpoint': 'saved/searches/[^/]*/embed', 'methods': ['POST']},
                     {'endpoint': 'saved/searches/[^/]*/unembed', 'methods': ['POST']},
                     {'endpoint': 'saved/searches/[^/]*/history', 'methods': ['GET'], 'oidEnabled': True},
                     {'endpoint': 'saved/searches/[^/]*/scheduled_times', 'methods': ['GET']},
                     {'endpoint': 'saved/searches/[^/]*/suppress', 'methods': ['GET']},
                     {'endpoint': 'scheduled/views', 'methods': ['GET']},
                     {'endpoint': 'scheduled/views/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'scheduled/views/[^/]*/dispatch', 'methods': ['POST']},
                     {'endpoint': 'scheduled/views/[^/]*/history', 'methods': ['GET']},
                     {'endpoint': 'scheduled/views/[^/]*/scheduled_times', 'methods': ['GET']},
                     {'endpoint': 'search/distributed/config', 'methods': ['GET']},
                     {'endpoint': 'search/distributed/config/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'search/distributed/peers', 'methods': ['POST', 'GET']},
                     {'endpoint': 'search/distributed/peers/[^/]*', 'methods': ['GET', 'DELETE', 'POST']},
                     {'endpoint': 'search/fields', 'methods': ['GET']},
                     {'endpoint': 'search/fields/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'search/fields/[^/]*/tags', 'methods': ['GET', 'POST']},
                     {'endpoint': 'search/intentionsparser', 'methods': ['GET', 'POST']},
                     {'endpoint': 'search/jobs', 'methods': ['GET', 'POST']},
                     {'endpoint': 'search/jobs/[^/]*', 'methods': ['GET', 'DELETE', 'POST'], 'oidEnabled': True},
                     {'endpoint': 'search/jobs/[^/]*/acl', 'methods': ['POST']},
                     {'endpoint': 'search/jobs/[^/]*/control', 'methods': ['POST']},
                     {'endpoint': 'search/jobs/[^/]*/events', 'methods': ['GET'], 'oidEnabled': True},
                     {'endpoint': 'search/jobs/[^/]*/results', 'methods': ['GET']},
                     {'endpoint': 'search/jobs/[^/]*/results_preview', 'methods': ['GET'], 'oidEnabled': True},
                     {'endpoint': 'search/jobs/[^/]*/search.log', 'methods': ['GET']},
                     {'endpoint': 'search/jobs/[^/]*/summary', 'methods': ['GET', 'GET', 'GET', 'GET']},
                     {'endpoint': 'search/jobs/[^/]*/timeline', 'methods': ['GET']},
                     {'endpoint': 'search/jobs/export', 'methods': ['GET']},
                     {'endpoint': 'search/parser', 'methods': ['GET', 'POST']},
                     {'endpoint': 'search/tags', 'methods': ['GET']},
                     {'endpoint': 'search/tags/[^/]*', 'methods': ['GET', 'POST', 'DELETE']},
                     {'endpoint': 'search/timeparser', 'methods': ['GET']},
                     {'endpoint': 'search/typeahead', 'methods': ['GET']},
                     {'endpoint': 'server/control', 'methods': ['GET']},
                     {'endpoint': 'server/control/restart', 'methods': ['POST']},
                     {'endpoint': 'server/info', 'methods': ['GET']},
                     {'endpoint': 'server/info/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'server/logger', 'methods': ['GET']},
                     {'endpoint': 'server/logger/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'server/settings', 'methods': ['GET']},
                     {'endpoint': 'server/settings/[^/]*', 'methods': ['GET', 'POST']},
                     {'endpoint': 'static/[^/]*', 'methods': ['GET']},
                     {'endpoint': 'storage/passwords', 'methods': ['POST', 'GET']},
                     {'endpoint': 'storage/passwords/[^/]*', 'methods': ['GET', 'DELETE', 'POST']}]


def precompile_whitelist():
    for props in _PROXY_WHITE_LIST:
        regex_string = '(^|^services/|^servicesns/[^/]+/[^/]+/)%s$' % props['endpoint']
        regex = re.compile(regex_string)
        props['endpoint'] = regex

precompile_whitelist()
from datetime import datetime

class ProxyController(BaseController):
    """/splunkd"""

    @route('/*_proxy_path')
    @expose_page(must_login=False, verify_session=False, methods=['GET', 'POST', 'PUT', 'DELETE'])
    def index(self, oid=None, **args):

        if cherrypy.request.method in ['POST', 'DELETE'] and not cherrypy.config.get('enable_proxy_write'):
            return self.generateError(405, _('Write access to the proxy endpoint is disabled.'))

        # We have to handle the fact that CherryPy is going to %-decode
        # the URL, including any "/" (%2F). As such, we use the relative_uri
        # (which doesn't %-decode %2F), and simply re-encode that URL
        logger.debug('[Splunkweb Proxy Traffic] %s request to: %s' % (cherrypy.request.method, cherrypy.request.relative_uri))
        relative_uri = cherrypy.request.relative_uri
        relative_uri = relative_uri[relative_uri.find("/splunkd")+9:]
        query_start = relative_uri.rfind("?")
        if (query_start > -1) and (cherrypy.request.query_string):
            relative_uri = relative_uri[:query_start]
        
        uri = urllib.quote(relative_uri)

        if uri.startswith('__raw/'):
            # Don't parse any response even if it's a 404 etc
            rawResult = True
            uri = uri[6:]
        else:
            rawResult = False

        endpointProps = self.getAllowedEndpointProps(uri, cherrypy.request.method)
        if endpointProps is None:
            # endpoint not allowed
            logger.info("Resource not found: %s" % uri)
            raise cherrypy.HTTPError(404, _('Resource not found: %s' % uri))

        # sessionKey extraction:
        # Use oid request param.
        if oid:
            if not endpointProps.get('oidEnabled', False):
                raise cherrypy.HTTPError(401, _('Splunk cannot authenticate the request. oid unsupported for this resource.'))
            sessionKey = oid
            logger.info('Using request param oid as app server sessionKey and removing from request.params')
            del cherrypy.request.params['oid']
        # Use cherrypy session object.
        else:
            sessionKey = cherrypy.session.get('sessionKey')
            cherrypy.session.release_lock()

        if not sessionKey:
            logger.info('proxy accessed without stored session key')
        
        # CSRF Protection
        requireValidFormKey = not endpointProps.get('skipCSRFProtection', False)
        if not util.checkRequestForValidFormKey(requireValidFormKey):
            # checkRequestForValidFormKey() will raise an error if the request was an xhr, but we have to handle if not-xhr
            raise cherrypy.HTTPError(401, _('Splunk cannot authenticate the request. CSRF validation failed.'))

        # Force URI to be relative so an attacker can't hit any arbitrary URL
        uri = '/' + uri

        if cherrypy.request.query_string:
            queryArgs = cherrypy.request.query_string.split("&")
            # need to remove the browser cache-busting _=XYZ that is inserted by cache:false (SPL-71743)
            modQueryArgs = [queryArg for queryArg in queryArgs if not queryArg.startswith("_=") and not queryArg.startswith("oid=")]
            uri += '?' + '&'.join(modQueryArgs)

        postargs = None
        body = None
        if cherrypy.request.method in ('POST', 'PUT'):
            content_type = cherrypy.request.headers.get('Content-Type', '')
            if not content_type or content_type.find('application/x-www-form-urlencoded') > -1:
                # We use the body_params to avoid mixing up GET/POST arguments,
                # which is the norm with output_mode=json in Ace.
                logger.debug('[Splunkweb Proxy Traffic] request body: %s' % cherrypy.request.body_params)
                postargs = cherrypy.request.body_params
            else:
                # special handing for application/json POST
                # cherrypy gives file descriptor for POST's
                body = cherrypy.request.body.read()
                logger.debug('[Splunkweb Proxy Traffic] request body: %s' % body)

        proxyMode = False
        if 'authtoken' in args:
            proxyMode = True

        simpleRequestTimeout = splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
        if 'timeout' in endpointProps:
                simpleRequestTimeout = endpointProps['timeout']

        try:
            serverResponse, serverContent = splunk.rest.simpleRequest(
                make_url(uri, translate=False, relative=True, encode=False),
                sessionKey,
                postargs=postargs,
                method=cherrypy.request.method,
                raiseAllErrors=True,
                proxyMode=proxyMode,
                rawResult=rawResult,
                jsonargs=body,
                timeout=simpleRequestTimeout
            )

            for header in serverResponse:
                cherrypy.response.headers[header] = serverResponse[header]

            # respect presence of content-type header
            if(serverResponse.get('content-type') == None):
                del cherrypy.response.headers['Content-Type']

            logger.debug('[Splunkweb Proxy Traffic] response status code: %s' % serverResponse.status)

            if serverResponse.messages:
                return self.generateError(serverResponse.status, serverResponse.messages)

            if rawResult:
                cherrypy.response.status = serverResponse.status

            logger.debug('[Splunkweb Proxy Traffic] response body: %s' % serverContent)
            return serverContent

        except splunk.RESTException, e:
            logger.exception(e)
            return self.generateError(e.statusCode, e.extendedMessages)

        except Exception, e:
            logger.exception(e)
            return self.generateError(500, su.escape(str(e)))


    def getAllowedEndpointProps(self, uri, method):
        '''verify that that a given uri and associated method is white listed to be proxied to the endpoint.'''

        uri = uri.lower()
        logger.debug("searching for uri: %s" % uri)
        for props in _PROXY_WHITE_LIST:
            if props['endpoint'].match(uri):
                #logger.debug("endpoint: %s" % props)
                #logger.debug("\n\n\nendpoint FOUND!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n\n\n")
                if method in props['methods']:
                    return props
        else:
            return None

    def generateError(self, status, messages=None):
        def generateErrorJson():
            cherrypy.response.headers['Content-Type'] = "application/json"
            output = {}
            output["status"] = su.escape(str(status))
            if messages:
                if isinstance(messages, list):
                    escaped_messages = [{"type":su.escape(msg['type']),"text":su.escape(msg['text'])} for msg in messages]
                    output["messages"] = escaped_messages
                else:
                    msg = {"type":"ERROR","text":su.escape(messages)}
                    output["messages"] = [msg]       
            return json.dumps(output)
        def generateErrorXml():            
            output = [splunk.rest.format.XML_MANIFEST, '<response>']
            output.append('<meta http-equiv="status" content="%s" />' % su.escape(str(status)))
            if messages:
                output.append('<messages>')
                
                if isinstance(messages, list):
                    for msg in messages:
                        output.append('<msg type="%s">%s</msg>' % (su.escape(msg['type']), su.escape(msg['text'])))
                else:
                    output.append('<msg type="ERROR">%s</msg>' % str(messages))
                output.append('</messages>')
                
            output.append('</response>')
            return '\n'.join(output)


        logger.debug('[Splunkweb Proxy Traffic] response errors: %s' % str(messages))
        output_mode = cherrypy.request.params.get("output_mode")
        # make sure that error status is relayed back to client via status code, and not just content
        cherrypy.response.status = status
        if output_mode and output_mode == "json":
            return generateErrorJson()
        return generateErrorXml()            


