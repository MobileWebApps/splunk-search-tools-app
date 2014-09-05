import cherrypy, json, logging
import splunk.util
from splunk.appserver.mrsparkle import *
from splunk.appserver.mrsparkle.lib import util, config

logger = logging.getLogger('splunk.appserver.controllers.config')

class ConfigController(BaseController):
    """/config"""

    #
    # exposed controllers
    #

    @route('/')
    @expose_page(must_login=False, methods='GET')
    # FIXME: the wildcard **kwargs is only for compatibility with the require.js shim, we should remove it when we don't need it
    def index(self, autoload=False, namespace=None, asDict=False, embed=False, **kwargs):
        '''
        Returns the configuration information for the main Splunk frontend.
        The values returned from the endpoint are subject to the following:
        
        1) values are idempotent
        2) any time values are in ISO-8601 format
        3) values are typed appropriately
        
        On the JS side, these values are all inserted into a config
        dictionary that is accessible at:
        
            window.$C[<key_name>]
            
        These values should be treated as read-only.
        
        TODO: attach event handlers to value changes on JS side
        
        '''
        
        # embed enabled handler
        embed = splunk.util.normalizeBoolean(embed)
        if embed:
            util.embed_modify_request()
        
        cherrypy.response.headers['content-type'] = splunk.appserver.mrsparkle.MIME_JSON
        
        args = config.getConfig(sessionKey=cherrypy.session.get('sessionKey'), namespace=namespace)

        # for debug page
        if asDict:
            return args
            
            
        if autoload:
            cherrypy.response.headers['Content-Type'] = 'application/javascript'
            output = 'window.$C = %s' % json.dumps(args)
        else:
            output = json.dumps(args)


        if util.apply_etag(output):
            return None
        else:
            logger.debug('config values: %s' % args)
            return output


    @route('/:var')
    @expose_page(methods='GET')
    def getvar(self, var, **kw):
        cfg = config.getConfig(sessionKey=cherrypy.session.get('sessionKey'), namespace=None)
        if not cfg.has_key(var):
            raise cherrypy.NotFound()
        return str(cfg[var])


    @expose_page(must_login=False, methods='GET', handle_api=True)
    def UI_UNIX_START_TIME(self, **kw):
        """/config/UI_UNIX_START_TIME is required without auth by the server restart command"""
        start_time = round(cherrypy.config.get('start_time', 0))
        if cherrypy.request.is_api:
            data = {'start_time': start_time}
            return self.render_json(data)
        else:
            cherrypy.response.headers['content-type'] = 'text/plain'
            return start_time
    
    @expose_page(must_login=False, methods='GET')
    def img(self, **kw):
        """
        Used by the javascript restart handler to determine when the server is back
        up when the protocol has changed
        """
        if 'proto' in kw:
            # IE8 will actually send an http request down its already open https pipe
            # if it can; test to make sure we're actually in the mode it thinks we are
            if kw['proto'] != cherrypy.request.scheme:
                raise cherrypy.HTTPError(400)
        img = file(os.path.join(cherrypy.config['staticdir'], 'img/skins/default/a.gif')).read()
        cherrypy.response.headers['content-type'] = 'image/gif'
        return img


    @expose_page(must_login=False, verify_sso=False, methods='GET')
    def version(self, **kw):
        return "Splunk;%s;%s" % (cherrypy.config.get('version_number', '4'), cherrypy.config.get('version_label', 'unknown'))

