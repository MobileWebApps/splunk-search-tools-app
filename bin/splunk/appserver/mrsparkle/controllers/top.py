import cherrypy
from cherrypy import expose
from splunk.appserver.mrsparkle import *
from splunk.appserver.mrsparkle.lib import util, i18n
import splunk.auth
import logging
import splunk.entity as en
import urlparse
from splunk.appserver.mrsparkle.lib.decorators import expose_page

# pull in active controllers
from account import AccountController
from admin import AdminController
from alerts import AlertsController
from alertswizard import AlertsWizardController
from alertswizardv2 import AlertsWizardV2Controller
from appnav import AppNavController
from config import ConfigController
from dashboardshare import DashboardShareController
from dashboardwizard import DashboardWizardController
from debug import DebugController
from embed import EmbedController
from field import FieldController
from lists import ListsController 
from messages import MessagesController
from module import ModuleController
from parser import ParserController
from paneleditor import PanelEditorController
from prototype import PrototypeController
from proxy import ProxyController
from search import SearchController
from tags import TagsController
from utility import UtilityController
from view import ViewController
from savedsearchredirect import SavedSearchRedirectController
from savesearchwizard import SaveSearchWizardController
from searchhelper import SearchHelperController
from ifx import IFXController
from etb import ETBController
from viewmaster import ViewmasterController
from report import ReportController
from scheduledigestwizard import ScheduleDigestWizardController
from wall import WallController
from tree import TreeController
from custom import CustomController
from scheduledviews import ScheduledViewController
from i18n_catalog import I18NCatalogController

# this must be imported after the controllers.
from lib.module import moduleMapper

logger = logging.getLogger('splunk.appserver.controllers.top')

class APIController(BaseController):
    pass

class TopController(BaseController):
    # set base endpoint controllers
    account = AccountController()
    # this change was for the URL structure. file is still admin.py
    manager = AdminController()
    api = APIController()
    app = ViewController()
    alerts = AlertsController()
    alertswizard = AlertsWizardController()
    alertswizardv2 = AlertsWizardV2Controller()
    config = ConfigController()
    appnav = AppNavController()
    dashboardshare = DashboardShareController()
    dashboardwizard = DashboardWizardController()
    debug = DebugController()
    embed = EmbedController()
    field = FieldController()
    lists = ListsController()
    messages = MessagesController()
    module = ModuleController()
    parser = ParserController()
    paneleditor = PanelEditorController()
    prototype = PrototypeController()
    search = SearchController()
    tags = TagsController()
    splunkd = ProxyController()
    util = UtilityController()
    savesearchwizard = SaveSearchWizardController()
    savedsearchredirect = SavedSearchRedirectController()
    scheduledigestwizard = ScheduleDigestWizardController()
    shelper = SearchHelperController()
    ifx = IFXController()
    etb = ETBController()
    viewmaster = ViewmasterController()
    report = ReportController()
    wall = WallController()
    tree = TreeController()
    custom = CustomController()
    scheduledview = ScheduledViewController()
    i18ncatalog = I18NCatalogController()   
 
    @expose
    def admin(self):
        '''
        redirect to manager in case old admin url is hit.
        '''
        self.redirect_to_url('/manager')
    
    @expose_page()
    def index(self):
        '''
        Serves the root of the webserver
        '''
        # If the license is expired, redirect to the licensing endpoint.
        # Since we have no way of determining if the user has permissions to change
        # licenses, there is still the chance that a basic user could hit the root
        # endpoint and get redirected to licensing by hitting "/" with an expired license.
        if cherrypy.config['license_state'] == 'EXPIRED':
            return self.redirect_to_url('/licensing', _qs={'return_to': cherrypy.request.relative_uri})
                
        return self.redirect_to_url('/app/%s' % splunk.auth.getUserPrefs('default_namespace'))
            
    @expose
    def login(self):
        """Legacy 3.x login url"""
        return self.redirect_to_url('/account/login')

    @expose
    def info(self):
        """
        Provides table of contents for all locally hosted resources
        """
        
        # gather all of the XML schema files
        dir = util.make_splunkhome_path(['share', 'splunk', 'search_mrsparkle', 'exposed', 'schema'])
        schemaFiles = [x[0:-4] for x in os.listdir(dir) if x.endswith('.rnc')]
        return self.render_template('top/info.html', {'schemaFiles': schemaFiles})
    
    @expose
    def licensing(self, return_to=None, **unused):
        return self.redirect_to_url('/manager/system/licensing/switch', _qs={'return_to': return_to})

    @expose
    def paths(self):
        """
        Generates an HTML page documenting accessible paths on this site
        and the methods responsible for generating them
        """
        mappings = util.urlmappings(self, cherrypy.request.script_name+'/', exclude=cherrypy.request.script_name+'/api') 
        mappings.sort(lambda a,b: cmp(a['path'], b['path']))
        paths = [ (i, data['path']) for (i, data) in enumerate(mappings) ]
        return self.render_template('top/paths.html', { 'pathnames' : paths, 'mappings' : mappings })

    @expose_page(must_login=True)
    def modules(self, **kwargs):
        """
        Generates an HTML page documenting all registered modules
        """
        definitions = moduleMapper.getInstalledModules()
        names = definitions.keys()
        names.sort()
        
        # pull out additional meta info
        groupedNames = []
        for module in definitions:
            definitions[module]['isAbstract'] = True if module.find('Abstract') > -1 else False
            definitions[module]['isPrototype'] = True if definitions[module]['path'].find('/prototypes') > -1 else False

            # get general classification from folder path
            group = 'Base'
            try:
                folders = definitions[module]['path'].split(os.sep)
                pivot = folders.index('search_mrsparkle')
                if pivot > -1 and folders[pivot + 1] == 'modules' and len(folders) > (pivot + 2):
                    group = folders[pivot + 2]
            except Exception, e:
                logger.error(e)
            groupedNames.append((group, module))
        groupedNames.sort()
        
            
        show_wiki = True if 'show_wiki' in kwargs else False
        return self.render_template('top/modules.html', {
            'modules': definitions, 
            'names': names , 
            'show_wiki': show_wiki, 
            'groupedNames': groupedNames
        })

    @expose
    @conditional_etag()
    def help(self, **kwargs):
        """
        Redirects user to context-sensitive help
        """
        
        locale = i18n.current_lang_url_component()
        location = kwargs.get('location','')
            
        params = {
            'location': location,        
            'license': 'free' if cherrypy.config.get('is_free_license') else 'pro',
            'installType': 'trial' if cherrypy.config.get('is_trial_license') else 'prod',
            'versionNumber': cherrypy.config.get('version_label'),
            'skin': 'default',
            'locale': locale
        }
        return self.render_template('top/help.html', {'help_args': params})

    @expose_page(must_login=False)
    def redirect(self, **kwargs):
        """
        Simple url redirector. Expects 'to' arg to contain the target url. External links must
        begin with the protocol.
        """
        referer = cherrypy.request.headers.get("Referer", "")
        base = cherrypy.request.base

        if not referer.startswith(base):
           raise cherrypy.HTTPError(403, _('Splunk will not redirect if the referring web page is not Splunk itself.')) 

        raise cherrypy.HTTPRedirect(kwargs.get('to'))
        
    @expose_page()
    def _bump(self, **kwargs):
        """
        Bumps push_version so that clients are forced to reload static resources.
        Static resources are currently under /static/@12345.  If the bump number
        is non-zero, then the URI becomes /static/@12345.6, where '6' is the
        bump number.
        
        Usage:
        
            POST /splunk/_bump
        """
        
        if cherrypy.request.method == 'POST':
            self.incr_push_version()
            logger.info('appserver static bump number set to %s' % self.push_version())
            return "Version bumped to %i" % self.push_version()
        return """<html><body>Current version: %i<br>
            <form method=\"post\">
            <input type="hidden" name="splunk_form_key" value="%s">
            <input type=\"submit\" value=\"Bump version\">
            </form></body></html>""" % (self.push_version(), cherrypy.session.get('csrf_form_key'))


# Copy TopControllers attributes into the APIController, except for api to avoid recursion
[ setattr(APIController, attr, TopController.__dict__[attr]) for attr in TopController.__dict__ if attr[:2]!='__' and attr!='api' ]
