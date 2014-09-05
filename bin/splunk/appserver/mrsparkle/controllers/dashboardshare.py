# coding=UTF-8
import cherrypy
from splunk.appserver.mrsparkle import *

logger = logging.getLogger('splunk.appserver.controllers.dashboardshare')

class DashboardShareController(BaseController):
    @route('/:action=new')
    @expose_page(must_login=True, methods='GET')
    def edit(self, action, **params):
        template_args = {}
        return self.render_template('dashboardshare/new.html', template_args)

    @route('/:action=create')
    @expose_page(must_login=True, methods='POST')
    def update(self, action, **params):
        template_args = {}
        success = True
        if success is False:
            return self.render_template('dashboardshare/new.html', template_args)
        return self.render_template('dashboardshare/success.html')

