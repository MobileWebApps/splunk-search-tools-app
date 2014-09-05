import os, copy, logging, time
import re
import splunk.bundle
import splunk.entity as en
import splunk.saved
import splunk.util
import splunk.search.Parser
import splunk.rest.payload

from splunk.appserver.mrsparkle import *

from splunk.appserver.mrsparkle.lib import util, viewconf, viewstate, jsonresponse, cached, appnav
from splunk.appserver.mrsparkle.lib.module import moduleMapper
from splunk.appserver.mrsparkle.lib.memoizedviews import memoizedViews
from splunk.appserver.mrsparkle import controllers
import controllers.report
from splunk import search
from lib.apps import local_apps
from lib import i18n

logger = logging.getLogger('splunk.appserver.controllers.view')

# define the splunkd entity path where views are stored
VIEW_ENTITY_CLASS = 'data/ui/views'

# define the prefix for qualified search names
SERVICES_PATH = '/services'

# define the default view for saved searches.
DEFAULT_DISPLAYVIEW = 'search'

class InvalidViewException(Exception):
    pass

class ViewController(BaseController):

    # /////////////////////////////////////////////////////////////////////////
    #  Supporting methods
    # /////////////////////////////////////////////////////////////////////////

    def __init__(self):
        '''
        Boot up the view controller

        The view system renders the views for the current user and namespace.
        Module definitions, including those registered inside apps, are cached
        inside this controller object (the long-lived instance held by
        cherrypy)
        '''

        super(ViewController,self).__init__()
        self.lastAppList = set([])


    def getAppManifest(self):
        '''
        Returns a dict of all available apps to current user
        '''

        output = cached.getEntities('apps/local', search=['disabled=false','visible=true'], count=-1)

        return output


    def getViewManifest(self, namespace, currentViewName=None, viewstate_id=None, refresh=0, availableViews=None):
        '''
        Returns a flat dict of all available views to current user and namespace.
        Iterate over this output to inspect the properties of the various views.
        '''

        if availableViews is None:
            output = {}

            # get available views to user/app
            memoizedViews.getAvailableViews(namespace, refresh, output, flash_ok=util.agent_supports_flash())
        else:
            output = availableViews

        #
        # handle sticky state params for current view
        # the load sequence (from lowest the highest priority) is:
        # 1) default defined in <module>.conf
        # 2) view configuration XML
        # 3) specified viewstate param set; _current if not specified
        #

        if currentViewName and currentViewName in output:

            currentUser = cherrypy.session['user'].get('name')

            try:
                persisted = viewstate.get(currentViewName, viewstate_id=viewstate_id, namespace=namespace, owner=currentUser)

            except splunk.ResourceNotFound:
                # just stop trying to load non-existent viewstates
                logger.warn('getViewManifest - unable to load requested viewstate id=%s' % viewstate_id)
                return output

            logger.debug('getViewManifest - loading overlay viewstate id=%s' % viewstate_id)

            # Make a deep copy to avoid modifying entries in the memoizedViews cache.
            output[currentViewName] = copy.deepcopy(output[currentViewName])

            rosters = output[currentViewName]['layoutRoster']

            keyedParams = output[currentViewName].get('keyedParamMap')

            for panelName in rosters:
                for currentModule in rosters[panelName]:

                    moduleId = currentModule['id']
                    if moduleId in persisted.modules:
                        for paramName in persisted.modules[moduleId]:
                            logger.debug('PERSISTENCE - override module=%s paramName=%s: %s ==> %s' % (
                                moduleId,
                                paramName,
                                currentModule['params'].get(paramName, 'UNDEFINED'),
                                persisted.modules[moduleId][paramName]
                            ))
                            currentModule['params'][paramName] = persisted.modules[moduleId][paramName]

        return output

    def getAppConfig(self, appName, appList, permalinkInfo, currentViewName=None, build_nav=True, availableViews=None):
        '''
        Returns a dict of properties for appName.
        '''

        # determine viewstate set
        viewstate_id = None
        if 'vs' in cherrypy.request.params:
            viewstate_id = cherrypy.request.params['vs']
        elif 'DATA' in permalinkInfo:
            viewstate_id = permalinkInfo['DATA']['vsid']

        # set default output
        output = {
            'is_visible': False,
            'label': appName,
            'nav': {},
            'can_alert': False,
            'available_views': self.getViewManifest(appName, currentViewName, viewstate_id=viewstate_id, availableViews=availableViews)
        }

        if appName != 'system':
            if appName not in appList:
                logger.warn(_('Splunk cannot load app "%s" because it could not find a related app.conf file.') % appName)
                return output

            appConfig = appList[appName]

            output['is_visible'] = splunk.util.normalizeBoolean(appConfig['visible'])
            output['label']      = splunk.util.normalizeBoolean(appConfig['label'])
            output['version']    = appConfig.get('version')


        # we will skip building nav regardless of build_nav if the view is escapable into HTML
        skip_nav = False
        if currentViewName and output['available_views']:
            currentView = output['available_views'].get(currentViewName)
            if self.isViewHTMLEscapable(currentView):
                logger.info("skip_nav=True since this view is escapable")
                skip_nav = True

        # get app nav
        if build_nav and not skip_nav:
            can_alert, searches = self.get_saved_searches(appName)
            if can_alert is not None:
                output['can_alert'] = can_alert
            output['nav'], tmp_dv, output['navColor'] = appnav.getAppNav(appName, output['available_views'], searches)

        else:
            output['nav'] = {}
            output['navColor'] = None

        return output

    def isViewHTMLEscapable(self, viewDict):
        """
        Returns True if the viewDict provided is for a simple XML view that can be escaped into HTML or an already escaped simple XML view
        """
        if viewDict:
            # the template argument is our only indicator in the view dict re: escapability
            if viewDict['template'] == '/dashboards/dashboard.html' or viewDict['template'] == 'view/dashboard_escaped_render.html':
                return True

        return False

    def filePathToUrl(self, filePath, pivotPath='modules'):
        '''
        Converts a filesystem path to a relative URI path, on the assumption that
        both paths contain a common pivot path segment
        '''

        parts = filePath.split(os.sep)
        try: pivot = parts.index(pivotPath)
        except: return False
        return '/' + os.path.join(*parts[pivot:]).replace('\\', '/')

    def _getTermsForSavedSearch(self, savedSearchName, namespace) :
        savedSearch = en.getEntity("saved/searches", savedSearchName, namespace=namespace)
        return savedSearch.get('qualifiedSearch', False)


    def _getCustomFiles(self, isSimpleXml, include_app_css_assets, currentViewConfig, app):
        # gather application and view specific static content
        # allowed css is 'application.css', then any css declared in viewConfig
        customCssList = []
        printCssList = []
        customJsList = []

        sourceApp = currentViewConfig['app']

        def normalize_relative_path(path):
            """
                Strip relative path components to prevent remote file inclusion
            """
            path = path.replace('/../', '/')
            if path[0:3] == '../': path = path[3:]
            return path

        def resolve_asset(filename, assetType, appName, forceApp=False):
            if filename:
                if not forceApp:
                    # Try to split the specified name into app and file. If it's specified
                    # in the form "<app>:<file>" (eg. "myapp:script.js") then try toload
                    # the file from the given app otherwise load it from the default app.
                    parts = filename.split(':', 1)
                    if len(parts) == 2 and parts[0] in local_apps:
                        resolved = resolve_asset(parts[1], assetType, parts[0], forceApp=True)
                        if resolved:
                            return resolved
                if appName in local_apps:
                    localApp = local_apps[appName]
                    if localApp and 'static' in localApp:
                        statics = localApp['static'].get(assetType, [])
                        if filename in statics:
                            return '/static/app/%s/%s' % (appName, filename)

        #allow js assets
        if isSimpleXml:
            allowedJs = ['dashboard.js']
        else:
            allowedJs = ['application.js']

        if local_apps[app].has_key('static'):
            appstatics = local_apps[app]['static'].get('js', [])
            for filename in appstatics:
                if filename in allowedJs:
                    customJsList.append("/static/app/%s/%s" % (app, filename))

        if isSimpleXml and currentViewConfig['dashboard'].customScript is not None:
            customJSs = currentViewConfig['dashboard'].customScript.split(',')
            for customJS in customJSs:
                if customJS is not None:
                    customJS = customJS.strip()
                    customJS = normalize_relative_path(customJS)
                    if customJS not in allowedJs:
                        fullPath = resolve_asset(customJS, 'js', sourceApp)
                        if fullPath:
                            customJsList.append(fullPath)

        #css assets
        if include_app_css_assets:
            allowedCss = [currentViewConfig.get('stylesheet')]
            if isSimpleXml:
                allowedCss.append('dashboard.css')
            else:
                allowedCss.append('application.css')

            allowedPrintCss = ['print.css']
            if local_apps[app].has_key('static'):
                appstatics = local_apps[app]['static'].get('css', [])
                for filename in appstatics:
                    if filename in allowedCss:
                        customCssList.append("/static/app/%s/%s" % (app,filename))
                    elif filename in allowedPrintCss:
                        printCssList.append("/static/app/%s/%s" % (app,filename))
                appPatches = local_apps[app]['patch'].get('css', [])
                for patch in appPatches:
                    customCssList.append(patch)

            if isSimpleXml and currentViewConfig['dashboard'].customStylesheet is not None:
                customCsss = currentViewConfig['dashboard'].customStylesheet.split(',')
                for customCss in customCsss:
                    customCss = customCss.strip()
                    if customCss is not None:
                        customCss = normalize_relative_path(customCss)
                        fullPath = resolve_asset(customCss, 'css', sourceApp)
                        if fullPath and not fullPath in customCssList:
                            customCssList.append(fullPath)

        return customCssList, printCssList, customJsList



    # /////////////////////////////////////////////////////////////////////////
    #  Main route handlers
    # /////////////////////////////////////////////////////////////////////////

    @route('/:app/:view_id/:action=converttohtml', methods='POST')
    @expose_page(methods='POST')
    def convertToHtml(self, app, view_id, action, xmlString=None, newViewID=None):
        # TODO if xmlString is None, convert the eai:data in view
        loaded = viewconf.loads(xmlString, newViewID, sourceApp=app)
        template = loaded['template']
        model = loaded['dashboard']

        appConfig = self.getAppConfig(app, self.getAppManifest(), {}, view_id, False)
        currentViewConfig = appConfig['available_views'].get(view_id)

        customCssList, printCssList, customJsList = self._getCustomFiles(True, True, currentViewConfig, app)

        return self.render_template(template, {'dashboard': model, 'customCssFiles': customCssList,
                                               'customJsFiles': customJsList, 'escapedOutput': True,
                                               'APP': dict(id=app), 'VIEW': dict(id=view_id)})


    @route('/:app')
    @expose_page()
    def appDispatcher(self, app, setup=None):
        '''
        Redirect user to the default view, as specified in the nav XML

        Include a check against the setup properties to determine if we need
        to redirect to the setup page instead.

        The 'setup' param indicates if this handler should redirect to
        the app setup page, if requested
        '''

        apps = self.getAppManifest()

        if not apps.has_key(app):
            cherrypy.response.status = 404
            return self.render_template('view/404_app.html', {'app':app, 'apps':apps})

        # locate default view
        views = self.getViewManifest(namespace=app, refresh=1)
        nav, defaultView, navColor = appnav.getAppNav(app, views, {})
        defaultViewUri = ['app', app, defaultView]

        # check the app's setup status
        if self.appRequiresSetup(apps[app]):
            return self.renderSetup(apps, app, defaultViewUri, not setup)

        # otherwise, continue to default view
        raise self.redirect_to_url(defaultViewUri)

    def appRequiresSetup(self, appObj):
        return appObj.getLink('setup') and appObj['configured'] == '0'

    def renderSetup(self, apps, app, bypassUrlParts, skipInterstitial):
        # show interstitial first
        if skipInterstitial:
            return self.render_template('view/app_setup.html', {'bypass_link': self.make_url(bypassUrlParts), 'app_label': apps[app]['label'], 'appList': apps})

        logger.info('requested app is unconfigured, redirecting; app=%s configured=%s setup=%s' % (app, apps[app]['configured'], apps[app].getLink('setup')))
        return self.redirect_to_url(['manager', app, 'apps', 'local', app, 'setup'], _qs={
            'action':'edit',
            'redirect_override': self.make_url(bypassUrlParts, translate=False)
            })
 
    @route('/:app/:p=@go')
    @expose_page()
    def redirect(self, app, **kwargs):
        '''
        Dispatches generic object requests to the appropriate view.  Currently
        used for redirecting saved searches and sids

        TODO: this needs to be app configurable
        '''
        view = None
        saved_search_not_found_output = {
            'not_found_str': _("The view you requested could not be found."),
            'explanation_str': _("The view has probably been deleted."),
            'url': None
        }
        saved_search_general_error = {
            'not_found_str': _("The view you requested could not be found."),
            'explanation_str': '',
            'url': None
        }

        def getViewForSavedSearch(savedSearchName, app, owner=None):
            if savedSearchName.startswith(SERVICES_PATH):
                saved = en.getEntity('saved/searches', '', uri=savedSearchName, namespace=app, owner=owner)
            else:
                saved = en.getEntity('saved/searches', savedSearchName, namespace=app, owner=owner)
            app = saved.get('request.ui_dispatch_app') or app
            view = saved.get('request.ui_dispatch_view') or saved.get('displayview') or saved.get('view') or DEFAULT_DISPLAYVIEW
            return app, view

        def redirect(app, view, options):
            return self.redirect_to_url(['app', app, view], _qs=options)

        if 's' in kwargs:
            try:
                app, view = getViewForSavedSearch(kwargs['s'], app)
            except splunk.ResourceNotFound, e:
                cherrypy.response.status = 404
                return self.render_template('/errors/missing_job.html', saved_search_not_found_output)
            except:
                cherrypy.response.status = 400
                return self.render_template('/errors/missing_job.html', saved_search_general_error)

            logger.info('loading saved search "%s" into view "%s"' % (kwargs['s'], view))

            # removes the sid explicitly if one is set, this allows @go to follow the regular view.py behavior
            if 'sid' in kwargs:
                del kwargs['sid']

        elif 'sid' in kwargs:
            logger.info('loading SID "%s"' % kwargs['sid'])

            try:
                job = splunk.search.getJob(kwargs['sid'])
            except splunk.ResourceNotFound, e:
                logger.warn('unable to load search job, SID "%s" not found' % kwargs['sid'])
                output = {
                    'not_found_str': _("The search you requested could not be found."),
                    'explanation_str': _("The search has probably expired or been deleted."),
                    'rerun_str': _("Clicking \"Rerun search\" will run a new search based on the expired search's search string in the expired search's original time period.  Alternatively, you can return back to Splunk."),
                    'url': None
                }

                if e.resourceInfo:
                    ss_namespace = e.resourceInfo.get('app')
                    ss_owner = e.resourceInfo.get('owner')
                    ss_name = e.resourceInfo.get('name')
                    ss_now = e.resourceInfo.get('dispatch.now')
                    ss_loc = e.resourceInfo.get('location')

                    if ss_namespace and ss_name:
                        url = ['app', ss_namespace, '@go']
                        qs = {'s': ss_name}
                        if ss_now:
                            qs['now'] = ss_now
                        output['url'] = self.make_url(url, _qs=qs)


                not_found_str = _("The search you requested could not be found.")
                explanation_str = _("The search has probably expired or been deleted.")
                rerun_str = _("Clicking \"Rerun search\" will run a new search based on the expired search's search string in the expired search's original time period.  Alternatively, you can return back to Splunk.")

                cherrypy.response.status = 404
                return self.render_template('/errors/missing_job.html', output)
            except splunk.AuthorizationFailed, e:
                output = {
                    'not_found_str': _("The search you requested could not be viewed."),
                    'explanation_str': _("You do not have permission for the search you requested."),
                    'url': None
                }
                cherrypy.response.status = 403
                return self.render_template('/errors/missing_job.html', output)
            except:
                cherrypy.response.status = 400
                output = {
                    'not_found_str': _("The search you requested could not be found."),
                    'explanation_str': "",
                    'url': None
                }
                return self.render_template('/errors/missing_job.html', output)

            if job.isSavedSearch and job.label:
                try:
                    app, view = getViewForSavedSearch(job.label, app)
                except splunk.ResourceNotFound, e:
                    cherrypy.response.status = 404
                    return self.render_template('/errors/missing_job.html', saved_search_not_found_output)
                except:
                    cherrypy.response.status = 400
                    return self.render_template('/errors/missing_job.html', saved_search_general_error)
                logger.info('search job was run by saved search scheduler, predefined view: %s' % view)

            else:
                try:
                    request = job.request
                    view = request.get('ui_dispatch_view', False)
                    if view:
                        logger.info('search job specified view: %s' % view)
                except AttributeError:
                    pass

                if not view:
                    view = DEFAULT_DISPLAYVIEW

        if view:
            if 'p' in kwargs:
                del kwargs['p']

            # optimization to render stock reports in a printer friendly view
            # that removes interactive chrome
            if kwargs.get('media') == 'print' and view == 'report_builder_display':
                view = 'report_builder_print'

            redirect(app, view, kwargs)

        raise cherrypy.HTTPError(400, _('The requested object is unknown. You must provide an sid or saved search as a query param. e.g. ?sid=<sid> or ?s=<saved search name>.'))

    def processPermalink(self, app, now, earliest, latest, remote_server_list, q, sid, s, view_id):
        """
        Take the q, s, sid parameters and generate a uniform data structure for handling it.
        """
        permalinkInfo = {}

        # PROCESSING ARGUMENTS FOR PERMALINK.

        # 1. Saved search name, aka 's'.
        if (isinstance(s,str) and s) :
            try:
                if s.startswith(SERVICES_PATH):
                    savedSearchObject = search.getSavedSearch('', uri=s, namespace=app, owner=cherrypy.session['user'].get('name'))
                else:
                    savedSearchObject = search.getSavedSearch(s, namespace=app, owner=cherrypy.session['user'].get('name'))
            except splunk.ResourceNotFound:
                msg = _('The saved search "%(savedSearchName)s" could not be found.') % {'savedSearchName': s}
                lib.message.send_client_message('error', msg)
            else:
                if savedSearchObject.get('disabled') == '1':
                    msg = _('The saved search "%(savedSearchName)s" is disabled.') % {'savedSearchName': s}
                    lib.message.send_client_message('error', msg)
                else:
                    # ensure that the saved search has a viewstate object to save stuff to
                    # -- if saved search is owned by another user and is publically read-only,
                    #    the auto viewstate will fail
                    # TODO #1 it seems odd to do this here rather than in resurrectFromSavedSearch
                    #      for instance HiddenSavedSearch will now not get the same treatment.
                    #      it's probably OK, but seems inconsistent.
                    if savedSearchObject.get('vsid') == None:
                        newVsid = viewstate.generateViewstateId(make_universal=True)
                        self.setViewstate(app, view_id, newVsid, _is_shared=True, _is_autogen=True)
                        savedSearchObject['vsid'] = newVsid
                        logger.info('Saved search "%s" has no viewstate; auto generating vsid=%s' % (s, newVsid))
                        try:
                            en.setEntity(savedSearchObject)
                        except splunk.AuthorizationFailed:
                            logger.warn('loaded a saved search without a viewstate; current user not authorized to generate viewstate')
                        except splunk.ResourceNotFound, e:
                            logger.warn('There was an error generating the view state object. The view will likely continue to work, but will not be able to persist its state.')
                        except Exception, e:
                            logger.exception(e)

                    # scaffold the fallback structure
                    context = {
                        'fullSearch': savedSearchObject.get('search'),
                        'baseSearch': savedSearchObject.get('search'),
                        'decompositionFailed': True,
                        'intentions': [],
                        'earliest': savedSearchObject.get('dispatch.earliest_time'),
                        'latest': savedSearchObject.get('dispatch.latest_time'),
                        's': s,
                        'name': savedSearchObject.name
                    }
                    # Someone forgot the ACL todo
                    # SPL-59182: allow user to edit report on report builder view
                    context['acl'] = savedSearchObject.get('eai:acl')


                    # TODO #2.  And obviously by pulling it up we would delete this line
                    context["vsid"] = savedSearchObject.get('vsid')

                    permalinkInfo['DATA'] = {'mode': 'saved', 'name': s, 'vsid': context["vsid"]}
                    permalinkInfo['toBeResurrected'] = context

        # 2. search Id.
        elif (sid) :
            try :
                job = splunk.search.getJob(sid=sid,sessionKey=cherrypy.session['sessionKey'])
                jsonableJob = job.toJsonable(timeFormat='unix')

                # See -- SPL-24020  Saving a report using relative time ranges such as "Previous business week" gives me epoch earliest and lastest times in the save dialog
                # to fix SPL-24020 it now only uses the earliestTime, latestTime from the job when the job was dispatched by the scheduler.
                #    Note: earliest/latest from the job are always absolute epochTime.
                #    in all other cases it will use the earliest, latest args from the client, which may be relative time terms.
                #    see SPL-24020 for further comments.
                earliestTime = None
                latestTime   = None

                request = jsonableJob.get("request")
                delegate = jsonableJob.get("delegate")

                if delegate:
                    earliestTime = jsonableJob.get("earliestTime")
                    latestTime   = jsonableJob.get("latestTime")

                    # handle the cases where the search was all time, or partially all time
                    if request:
                        # if there was no latest time set, treat the lastest time as the time the search was run
                        # if there was no earliest time set, make sure we clear the earliest time

                        if not request.get("latest_time"):
                            latestTime = jsonableJob["createTime"]

                        if not request.get("earliest_time"):
                            earliestTime = None

                elif request:
                    earliestTime = request.get("earliest_time")
                    latestTime   = request.get("latest_time")
                else :
                    logger.error("Found job with no delegate that also had no request parameter. Unable to resurrect earliest and latest times.")

                context = {
                    'fullSearch': job.search,
                    'baseSearch': job.search,
                    'decompositionFailed': True,
                    'intentions': [],
                    'earliest': earliestTime,
                    'latest': latestTime
                    }

                # try to get the relevant viewstate; first check the URI, if not
                # passed, then check if job was dispatched from a saved search;
                # if so, try to pull the persisted viewstate id
                context["job"] = jsonableJob
                savedSearchName = None
                if 'vs' in cherrypy.request.params:
                    context["vsid"] = cherrypy.request.params['vs']
                else:
                    savedSearchObject = splunk.saved.getSavedSearchFromSID(sid)
                    if savedSearchObject:
                        savedSearchName = savedSearchObject.name

                        vsid = savedSearchObject.get('vsid')
                        if vsid and len(vsid) > 0:
                            context['vsid'] = savedSearchObject['vsid']

                permalinkInfo['DATA'] = {'mode': 'sid', 'name': savedSearchName, 'sid': sid, 'vsid': context.get('vsid')}
                permalinkInfo['toBeResurrected'] = context

            except splunk.AuthorizationFailed:
                lib.message.send_client_message('error', _('Permission to access job with sid = %(sid)s was denied.') % {'sid': sid})

            except splunk.ResourceNotFound :
                lib.message.send_client_message('error', _('Splunk cannot find a job with an sid = %(sid)s. It may have expired or been deleted.') % {'sid': sid})


        # 3) straight up search language string + any manually passed in getargs.
        elif (q):
            # scaffold the fallback structure
            permalinkInfo['toBeResurrected'] = {
                    'fullSearch': q,
                    'baseSearch': q,
                    'decompositionFailed': True,
                    'intentions': [],
                    'earliest': earliest,
                    'latest': latest
                    }

            if 'vs' in cherrypy.request.params:
                permalinkInfo['toBeResurrected']["vsid"] = cherrypy.request.params['vs']

        return permalinkInfo

    def buildViewTemplate(self, app, view_id, action=None, q=None, sid=None, s=None, earliest=None, latest=None, remote_server_list=None, render_invisible=False, build_nav=True, now=None, include_app_css_assets=True, appManifest=None, availableViews=None):
        """
        Build the template args required to render a view
        The render() handler below calls this, as do other controllers that need to embed a view
        into their own templates (see the AdminController for example)
        """

        # assert on view name; may only be alphanumeric, dot, dash, or underscore
        view_id_checker = re.compile('^[\w\.\-\_]+$')
        if not view_id_checker.match(view_id):
            raise cherrypy.HTTPError(400, _('Invalid view name requested: "%s". View names may only contain alphanumeric characters.') % view_id)

        # get list of all UI apps
        if appManifest is None:
            appList = self.getAppManifest()
        else:
            appList = appManifest

        appListKeys = set([])

        #check if the list of all UI apps matches the list of already seen UI apps
        #if not, go and reset the list of installed modules
        for k, v in appList.iteritems():
            version = v.get('version', '') or ''
            newKey = k + version
            appListKeys.add(newKey)

        appListDiff = self.lastAppList.symmetric_difference(appListKeys)
        if len(appListDiff):
            self.lastAppList = appListKeys
            moduleMapper.resetInstalledModules()

        permalinkInfo = self.processPermalink(app, now, earliest, latest, remote_server_list, q, sid, s, view_id)

        # get current app configuration
        appConfig = self.getAppConfig(app, appList, permalinkInfo, view_id, build_nav, availableViews=availableViews)

        if not appConfig['is_visible'] and not render_invisible:
            # if the user is trying to access an inaccessible launcher app, redirect to the default app
            if app.lower() == "launcher":
                logger.info("User requested page in inaccessible launcher app. Redirecting to default app.")
                return self.redirect_to_url('/app/%s' % splunk.auth.getUserPrefs('default_namespace'))

            raise cherrypy.HTTPError(404, _('App "%s" does not support UI access.  See its app.conf for more information.') % appConfig['label'])

        # get all views for current user in app context
        availableViews = appConfig['available_views']
        if len(availableViews) == 0:
            raise cherrypy.HTTPError(404, _('App "%s" does not have any available views.') % app)

        # get template layout for current config
        currentViewConfig = availableViews.get(view_id)
        if not currentViewConfig:
            raise cherrypy.HTTPError(404, _('Splunk cannot find the  "%s" view.') % view_id)

        if currentViewConfig.get('objectMode') == 'XMLError' and currentViewConfig.get('message'):
            raise cherrypy.HTTPError(400, _('XML Syntax Error: %s' % currentViewConfig.get('message')))

        # get asset rosters
        moduleMap = currentViewConfig.get('layoutRoster', {})
        cssList = []
        jsList = []
        for moduleName in currentViewConfig.get('activeModules', []):
            moddef = moduleMapper.getInstalledModules()[moduleName]
            if 'css' in moddef:
                cssList.append(self.filePathToUrl(moddef['css']))
            if 'js' in moddef:
                jsList.append(self.filePathToUrl(moddef['js']))

        # compile link list for all available views
        viewList = [{'label': availableViews[k].get('label', k), 'uri': self.make_url(['app', app, k])} for k in availableViews]
        viewList.sort(lambda x,y: cmp(x['label'], y['label']))



        #first we must iterate over local_apps to make sure the curent app is included
        if not app in local_apps:
            local_apps.refresh(True)
            if not app in local_apps:
                raise cherrypy.HTTPError(404, _('App  "%s" does not exist.') % app)

        isSimpleXml = 'dashboard' in currentViewConfig and isinstance(currentViewConfig['dashboard'], splunk.models.view_escaping.dashboard.SimpleDashboard)

        customCssList, printCssList, customJsList = self._getCustomFiles(isSimpleXml, include_app_css_assets, currentViewConfig, app)


        # translate the view label
        label = currentViewConfig.get('label')
        if label:
            label = _(label)
        else:
            label = '(%s)' % view_id

        # Safely get the displayView. Somehow this gets set to None elsewhere
        # which causes some problems further up in the stack
        displayView = currentViewConfig.get('displayView')
        if displayView == None:
            displayView = view_id

        # should we decompose our search?
        if currentViewConfig.get('decomposeIntentions') and 'toBeResurrected' in permalinkInfo:
            tbr = permalinkInfo['toBeResurrected']
            decomposed = util.resurrectSearch(hostPath = self.splunkd_urlhost,
                                              q = tbr['fullSearch'],
                                              earliest = tbr['earliest'],
                                              latest = tbr['latest'],
                                              remote_server_list = None,
                                              namespace = app,
                                              owner=cherrypy.session['user'].get('name'))
            tbr.update(decomposed)

        # assemble the template vars
        templateArgs = {

            # define standard params
            'APP': {'id': app, 'label': appConfig['label'], 'is_visible': appConfig['is_visible'], 'can_alert': appConfig['can_alert']},
            'VIEW': {'id': view_id,
                     'label': label,
                     'displayView': displayView,
                     'refresh': currentViewConfig.get('refresh', 10),
                     'onunloadCancelJobs': currentViewConfig.get('onunloadCancelJobs'),
                     'autoCancelInterval': currentViewConfig.get('autoCancelInterval'),
                     'template': currentViewConfig.get('template', []),
                     'objectMode': currentViewConfig.get('objectMode'),
                     'nativeObjectMode': currentViewConfig.get('nativeObjectMode'),
                     'hasAutoRun': currentViewConfig.get('hasAutoRun'),
                     'editUrlPath': currentViewConfig.get('editUrlPath'),
                     'canWrite': currentViewConfig.get('canWrite'),
                     'hasRowGrouping': currentViewConfig.get('hasRowGrouping'),
                    },
            'DATA': {'mode': None},
            'toBeResurrected': None,
            'dashboard': currentViewConfig.get('dashboard', {}),

            # define HTML asset params
            'navConfig': appConfig['nav'],
            'appList': appList,
            'viewList': viewList,
            'modules':  moduleMap,
            "cssFiles" : cssList,
            "customCssFiles" : customCssList,
            "printCssFiles" : printCssList,
            "jsFiles"  : jsList,
            "customJsFiles": customJsList,
            'splunkReleaseVersionParts': self._normalizedVersions(splunk.getReleaseVersion()),
            "make_static_app_url": self.make_static_app_url_closure(app)
        }

        if appConfig.get('navColor'):
            templateArgs['navColor'] = appConfig.get('navColor')

        if 'DATA' in permalinkInfo:
            templateArgs['DATA'] = permalinkInfo['DATA']

        if 'toBeResurrected' in permalinkInfo:
            templateArgs['toBeResurrected'] = permalinkInfo['toBeResurrected']

        return templateArgs

    def _normalizedVersions(self, version):
        """
        Takes a loosely defined version number, replaces all word characters to underscores and returns in order matching variants.

        Ex:
        version: 4.2.2
        matches:
        ['4', '4_2', '4_2_2']
        """

        version_delim = '_'
        version = re.sub("([^\w]+)", version_delim, version) #"elvis@#$#@$4.4" -> "elvis_4_4"
        version_parts = version.split(version_delim)
        version_name = None
        versions = []

        for version_part in version_parts:
            if version_name is None:
                version_name = version_part
            else:
                version_name = version_name + version_delim + version_part
            versions.append(version_name)
        return versions

    def make_static_app_url_closure(self, app):
        def make_static_app_url(path, *a, **kw):
            return util.make_url(['static', 'app', app, path], *a, **kw)
        return make_static_app_url


    def bypass_module_system(self, app, view_id, appManifest, availableViews):
        if app == 'system':
            return False
        if app not in appManifest:
            return False
        appConfig = appManifest[app]
        if not splunk.util.normalizeBoolean(appConfig['visible']):
            return False
        if len(availableViews) == 0:
            return False
        currentViewConfig = availableViews.get(view_id)
        if not currentViewConfig:
            return False
        if currentViewConfig.get('objectMode') == 'XMLError' and currentViewConfig.get('message'):
            return False
        if currentViewConfig.get('type') == 'redirect' and currentViewConfig.get('target') or currentViewConfig.get('type') == 'html':
            return True
        return False

    def renderStaticHTMLView(self, path):
        with open(path, 'rb') as f:
            cherrypy.response.headers['content-type'] = MIME_HTML
            yield f.read()

    def get_saved_searches(self, app):
        can_alert = None
        try:
            # Customers with 3k+ savedsearches run into high cpu and memory usage
            # count should be left at 500.
            searches = en.getEntities('saved/searches', namespace=app, search='is_visible=1 AND disabled=0', count=500, _with_new='1')
            if '_new' in searches:
                can_alert = 'alert.severity' in searches['_new'].get('eai:attributes', {}).get('optionalFields', [])
                del searches['_new']
        except splunk.ResourceNotFound:
            logger.warn('Unable to retrieve current saved searches')
            searches = {}
        return can_alert, searches

    @route('/:app/:view_id')
    @expose_page(handle_api=True, respect_permalinks=True)
    @set_cache_level('never')
    def render(self, app, view_id, action=None, q=None, sid=None, s=None, earliest=None, latest=None, remote_server_list=None, now=None, output='html', setup=None, **kw):
        '''
        Handle main view requests
        '''

        #
        # DEBUG
        #

        if output == 'pdf':
            # make a sub-request to the pdf report controller
            ctrl = cherrypy.request.app.root.report
            prefix = util.generateBaseLink()
            try:
                session_key = cherrypy.session['sessionKey']
                owner = cherrypy.session['user']['name']
                paperSize = kw.get('papersize', 'letter')
                paperOrientation = kw.get('orientation', 'portrait')
                cherrypy.session.release_lock()
                return ctrl.requestPDF(session_key=session_key,
                    owner = owner,
                    request_path = prefix + util.current_url_path(False),
                    override_disposition = 'inline; filename="dashboard.pdf"',
                    papersize=paperSize,
                    orientation=paperOrientation
                    )
            except controllers.report.SimpleError, e:
                # render an HTML version of the dashboard instead, including the PDF error
                lib.message.send_client_message('error', _("An error occurred while rendering the PDF: ")+e._message)
                output = 'html'
                # fall through to HTML renderer

        showsource = None
        if 'showsource' in kw:
            if kw['showsource'] in ('', 'html'): # ?showsource and ?showsource=html
                showsource = 'html'
            elif kw['showsource'] == 'advanced': # ?showsource=advanced
                showsource = 'advanced'
            else:
                showsource = 'invalid'

        if showsource:
            entity = en.getEntity(VIEW_ENTITY_CLASS, view_id, namespace=app)
            templateArgs = None
            if entity.get('eai:type') != 'html':
                templateArgs = {'viewConfig': viewconf.loads(entity.get('eai:data'), view_id,
                                                             isStorm=splunk.util.normalizeBoolean(
                                                                 cherrypy.config.get('storm_enabled')),
                                                             forceLegacyParser=(showsource == 'advanced'),
                                                             sourceApp=entity.get('eai:acl', {}).get('app', None)),
                                'view_id': view_id}

            if showsource == 'invalid':
                if entity.get('eai:type') == 'html' or 'isSimpleXML' in templateArgs['viewConfig']:
                    logger.debug('Redirecting invalid show source request to ?showsource')
                    raise cherrypy.HTTPRedirect(self.make_url(['app',app,view_id]) + '?showsource')
                else:
                    logger.debug('Redirecting invalid show source request to ?showsource=advanced')
                    raise cherrypy.HTTPRedirect(self.make_url(['app',app,view_id]) + '?showsource=advanced')

            if showsource == 'advanced':
                if entity.get('eai:type') == 'html':
                    if showsource == 'advanced':
                        raise cherrypy.HTTPError(500, 'Invalid view type for Advanced XML source view')

                try:
                    templateArgs['viewXml'] = viewconf.dumps(templateArgs['viewConfig'])
                except Exception, e:
                    logger.exception(e)
                    templateArgs['viewXml'] = '(unable to generate XML: %s)' % e

                return self.render_template('/view/pyramid.html', templateArgs)

        if kw.get('showtree'):
            viewConfig = viewconf.loads(en.getEntity(VIEW_ENTITY_CLASS, view_id, namespace=app).get('eai:data'), view_id, isStorm=splunk.util.normalizeBoolean(cherrypy.config.get('storm_enabled')))

            def convertModuleToJit(module):
                newModule = {
                    'id': '',
                    'name': '',
                    'children': []
                }

                if 'className' in module:
                    newModule['name'] = module['className']
                    if module['className'] in seenModules:
                        seenModules[module['className']] += 1
                    else:
                        seenModules[module['className']] = 1
                    newModule['id'] = '_'.join([module['className'], str(seenModules[module['className']])])

                if 'children' in module:
                    for childModule in module['children']:
                        newModule['children'].append(convertModuleToJit(childModule))
                return newModule


            seenModules = {}
            moduleTree = [{'id': 'root', 'name': 'root', 'children': []}]
            if 'modules' in viewConfig.keys():
                for module in viewConfig['modules']:
                    moduleTree[0]['children'].append(convertModuleToJit(module))

            templateArgs = {'moduleTree': moduleTree}
            return self.render_template('/view/tree2.html', templateArgs)

        time1 = time.time()
        availableViews = {}
        appManifest = self.getAppManifest()

        # SPL-76671 Go to setup screen if app is not yet configured
        # check the app's setup status
        if app in appManifest and self.appRequiresSetup(appManifest[app]):
            return self.renderSetup(appManifest, app, ['app', app], not setup)

        memoizedViews.getAvailableViews(app, 0, availableViews, flash_ok=util.agent_supports_flash())
        currentView = availableViews.get(view_id)

        if self.bypass_module_system(app, view_id, appManifest, availableViews):
            logger.info('bypass module system fast path')
            currentView = availableViews.get(view_id)
            # this handles 303 redirect
            if currentView.get('type') == 'redirect' and currentView.get('target'):
                 raise cherrypy.HTTPRedirect(self.make_url(['app', app, currentView.get('target')]) + '?' + cherrypy.request.query_string)
            # standard non-module page
            template = currentView.get('template', '')
            html = currentView.get('dashboard', '')
            # SPL-82587, since these encoded names need to be matched in javascript
            #            don't encode *~!() as the javascript encodeURIComponent() function
            #            doesn't encode them
            app_url_encoded = urllib.quote(app, safe='*!~()')
            user_url_encoded = urllib.quote(cherrypy.session['user'].get('name'), safe='*!~()')

            # get the app nav
            can_alert, searches = self.get_saved_searches(app)
            app_nav_views, default_view, app_nav_color = appnav.getAppNav(app, availableViews, searches)

            # apps local for the current app (partial splunkd payload)
            apps_local = splunk.rest.payload.scaffold()
            apps_local['entry'][0]['content']['version'] = appManifest[app].get('version')
            apps_local_disable_link = appManifest[app].getLink('disable')
            if apps_local_disable_link:
                apps_local['entry'][0]['links']['disable'] = apps_local_disable_link

            # fake app nav resource (partial splunkd payload)
            app_nav = splunk.rest.payload.scaffold()
            app_nav['entry'][0]['content']['nav'] = app_nav_views
            app_nav['entry'][0]['content']['color'] = app_nav_color
            app_nav['entry'][0]['content']['defaultView'] = default_view
            app_nav['entry'][0]['content']['label'] = appManifest[app].get('label', app)

            # server info
            server_info = splunk.rest.payload.scaffold()
            server_info['entry'][0]['content']['isFree'] = cherrypy.config['is_free_license']
            server_info['entry'][0]['content']['isTrial'] = cherrypy.config['is_trial_license']
            server_info['entry'][0]['content']['version'] = cherrypy.config['version_number']
            server_info['entry'][0]['content']['guid'] = cherrypy.config['guid']
            server_info['entry'][0]['content']['build'] = cherrypy.config['build_number']
            server_info['entry'][0]['content']['product_type'] = cherrypy.config['product_type']
            server_info['entry'][0]['content']['serverName'] = cherrypy.config['serverName']

            # splund partial payloads where link alternate is the primary key
            splunkd = {}
            splunkd['/servicesNS/nobody/system/apps/local/%s' % app_url_encoded] = apps_local
            splunkd['/servicesNS/%s/%s/apps/nav' % (user_url_encoded, app_url_encoded)] = app_nav
            splunkd['/services/server/info'] = server_info

            # SPL-62389
            # https://github.com/h5bp/html5-boilerplate/issues/378
            cherrypy.response.headers['X-UA-Compatible'] = 'IE=Edge'

            time2 = time.time()
            output = self.render_template(template, {'app': app, 'page': view_id, 'dashboard': html, 'splunkd': splunkd})
            time3 = time.time()
            logger.info('PERF - viewType=fastpath viewTime=%ss templateTime=%ss' % (round(time2-time1, 4), round(time3-time2, 4)))
            return output

        templateArgs = self.buildViewTemplate(app, view_id, action, q, sid, s, earliest, latest, remote_server_list, now=now, appManifest=appManifest, availableViews=availableViews)
        if showsource == 'html':
            templateArgs['escapedOutput'] = True

        time2 = time.time()
        try:
            output = self.render_template('/view/' + templateArgs['VIEW']['template'], templateArgs)
        # If we couldn't render the template from the global view templates then
        # it is likely an app specified template.
        # TODO: Leverage mako lookups to handle to order of directories so we
        # don't have to do this.
        except:
            output = self.render_template(templateArgs['VIEW']['template'], templateArgs)
        time3 = time.time()
        logger.info('PERF - viewType=modules viewTime=%ss templateTime=%ss' % (round(time2-time1, 4), round(time3-time2, 4)))

        if showsource == 'html':
            if templateArgs['VIEW']['template'] != '/dashboards/dashboard.html'and \
                            templateArgs['VIEW']['template'] != 'view/dashboard_escaped_render.html':
                if kw['showsource'] == '':
                    raise cherrypy.HTTPRedirect(self.make_url(['app',app,view_id]) + '?showsource=advanced')
                else:
                    raise cherrypy.HTTPError(500, 'Invalid view type for HTML source view')
            return self.render_template('/view/dashboard_escaped.html', dict(
                page = "showhtml",
                view_id = "showhtml",
                view_name = view_id,
                view_type = entity.get('eai:type'),
                escapedHTML = output,
                splunkd = None
            ))

        if cherrypy.request.is_api:
            # set non json serializable types to None revisit if required.
            for i in templateArgs['appList']:
                templateArgs['appList'] = None
            templateArgs['make_url'] = None
            templateArgs['make_route'] = None
            templateArgs['attributes'] = None
            templateArgs['controller'] = None
            templateArgs['make_static_app_url'] = None
            templateArgs['h'] = None
            return self.render_json(templateArgs)
        else:
            cherrypy.response.headers['content-type'] = MIME_HTML
            return output

    @route('/:app/:view_id/:action=edit', methods='GET')
    @expose_page(handle_api=True, methods='GET')
    def renderEditMode(self, app, view_id, action, **kwargs):
        return self.render(app, view_id)

    @route('/:app/:view_id/:viewstate_id', methods='GET')
    @expose_page(handle_api=True, methods='GET')
    def getViewstate(self, app, view_id, viewstate_id):
        '''
        Returns a JSON structure representing all of the module params for
        view_id.
        '''

        try:
            viewManifest = self.getViewManifest(namespace=app, currentViewName=view_id, viewstate_id=viewstate_id)
        except splunk.ResourceNotFound:
            raise cherrypy.HTTPError(status=404, message=(_('Viewstate not found; view=%s viewstate=%s') % (view_id, viewstate_id)))


        currentView = viewManifest[view_id]

        output = {}

        for panelName in currentView['layoutRoster']:
            for currentModule in currentView['layoutRoster'][panelName]:
                output[currentModule['id']] = currentModule.get('params', {})

        return self.render_json(output)



    @route('/:app/:view_id/:viewstate_id')
    @expose_page(handle_api=True, methods=['GET','POST'])
    def setViewstate(self, app, view_id, viewstate_id, _is_shared=False, _is_autogen=False, **form_args):
        '''
        Persists module params to the specific viewstate object.  Writes are
        done in an overlay fashion; unspecified params will not be overwritten.
        Parameters are accepted in the following format:

            <module_DOM_id>.<param_name>=<param_value>

        Ex:

            SearchBar_0_0_0.useTypeahead=true

        Only string values are accepted; complex data types are not persistable.
        '''

        output = jsonresponse.JsonResponse()

        # determine the desired viewstate
        altView, vsid = viewstate.parseViewstateHash(viewstate_id)
        if altView == None:
            altView = view_id

        # scaffold object mapper
        vs = viewstate.Viewstate()
        vs.namespace = app
        vs.view = altView
        vs.id = vsid

        if splunk.util.normalizeBoolean(_is_shared):
            vs.owner = 'nobody'
        else:
            vs.owner = cherrypy.session['user'].get('name')

        # add in stub property
        if _is_autogen and len(form_args) == 0:
            form_args['is.autogen'] = 1

        if len(form_args) == 0:
            logger.warn('setViewstate - no parameters received; nothing persisted')
            output.success = False
            output.addError(_('No parameters received; aborting'))
            return self.render_json(output)

        # insert all passed params
        for key in form_args:
            parts = key.split('.', 1)
            if len(parts) < 2:
                logger.warn('setViewstate - invalid viewstate param name: %s; aborting' % key)
                output.success = False
                output.addError(_('Invalid viewstate param name: %s; aborting') % key)
                return self.render_json(output)

            vs.modules.setdefault(parts[0], {})
            vs.modules[parts[0]][parts[1]] = form_args[key]
            logger.debug('setViewstate - setting module=%s param=%s value=%s' % (parts[0], parts[1], form_args[key]))

        # commit
        try:
            viewstate.commit(vs)
        except Exception, e:
            logger.exception(e)
            output.success = False
            output.addError(str(e))
            return self.render_json(output)


        # set sharing bit, if requested; should succeed even for normal users
        if splunk.util.normalizeBoolean(_is_shared):
            try:
                viewstate.setSharing(vs, 'global')
            except Exception, e:
                logger.exception(e)
                output.success = False
                output.addError(str(e))
                return self.render_json(output)

        return self.render_json(output)

    @route('/:app/:view_id/:action=strings', methods='GET')
    @expose_page(methods='GET')
    def getI18NStrings(self, app, view_id, action, **kwargs):
        strings = i18n.generate_wrapped_js(view_id)
        return self.render_template('view/jsonDefine.html', {'jsonData': strings})
