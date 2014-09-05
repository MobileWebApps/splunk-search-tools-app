# coding=UTF-8
import cherrypy
from splunk.appserver.mrsparkle import *

logger = logging.getLogger('splunk.appserver.controllers.embed')

class EmbedController(BaseController):
    
    @route('/')
    @set_cache_level('never')
    @expose_page(must_login=False, methods='GET', embed=True)
    def index(self, **params):
        cherrypy.response.headers.pop('X-Frame-Options', None)
        data = {
            'app': '-',
            'page': 'embed',
            'splunkd': {}
        }
        return self.render_template('pages/base.html', data)

