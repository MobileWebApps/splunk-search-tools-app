"""
App installation/upgrade controller
lives at /manager/appinstall
"""

import cherrypy
import urllib
from splunk.appserver.mrsparkle import *
from splunk.appserver.mrsparkle.lib import cached, module
from splunk.appserver.mrsparkle.lib.memoizedviews import memoizedViews
from splunk.appserver.mrsparkle.lib.util import parse_breadcrumbs_string
from splunk.appserver.mrsparkle.lib.util import reset_app_build
from splunk.appserver.mrsparkle.lib.statedict import StateDict
from splunk.appserver.mrsparkle.lib.msg_pool import MsgPoolMgr, UI_MSG_POOL
import splunk.rest as rest
import splunk.entity as en
import xml.etree.cElementTree as et
import os, os.path, copy, cgi, tempfile, shutil
import splunk

APP_INSTALL_TIMEOUT = 600

class SBLoginException(Exception): pass
class SBInvalidLoginException(SBLoginException): pass
class SBNotConnectedException(SBLoginException): pass
class SBFileUploadException(Exception): pass


class AppInstallController(BaseController):

    def getLocalApp(self, appid, flush_cache=True):
        """
        Fetch details on a locally installed app, optionally ensuring the cache is flushed first
        """
        local_apps = cached.getEntities('apps/local', count=-1, __memoized_flush_cache=flush_cache)
        appid = appid.lower()
        for id, app in local_apps.iteritems():
            if id.lower() == appid:
                return app
        return None

    def splunkbaseLogin(self, username, password):
        try:
            response, content = rest.simpleRequest('/apps/remote/login', postargs={'username' : username, 'password' : password}, sessionKey=cherrypy.session['sessionKey'])
        except splunk.SplunkdConnectionException as e:
            logger.error("Splunkd connection error: %s" % e)
            raise SBNotConnectedException()
        except splunk.AuthorizationFailed as e:
            logger.warn("Invalid credentials: %s" % e)
            raise SBInvalidLoginException()

        if response.status == 400:
            logger.warn("Invalid Splunkbase credentials")
            raise SBInvalidLoginException()

        if response.status not in [200, 201]:
            return None
            
        root = et.fromstring(content)
        sbKey = cherrypy.session['sbSessionKey'] = root.findtext('sessionKey')

        return sbKey

    def getSBSessionKey(self):
        """
        Fetch the user's logged in splunkbase session key
        """
        return cherrypy.session.get('sbSessionKey')

    def getRemoteAppEntry(self, appid):
        """
        Used to determine whether the app is available on Splunkbase and whether splunkd can even talk to Splunkbase
        """
        return en.getEntity('/apps/remote/entriesbyid', appid, sessionKey=cherrypy.session['sessionKey'])

    def isRestartRequired(self):
        """Query the messages endpoint to determine whether a restart is currently required"""
        try:
            rest.simpleRequest('/messages/restart_required', sessionKey=cherrypy.session['sessionKey'])
            return True
        except splunk.ResourceNotFound:
            return False

    def appNeedsSetup(self, app):
        """Returns true if the passed in app needs to be setup to continue"""
        return app.getLink('setup') and app['configured'] == '0'

    def appUpgradeAvailable(self, app):
        """Returns true if the passed in app has an upgrade available for install from Splunkbase"""
        return app.getLink('update')

    def appIsDisabled(self, app):
        """Returns true if the app is disabled"""
        return app['disabled'] == '1'

    def getSetupURL(self, appid, state):
        """Build the URL to an app's setup page, setting the return url to be this controller's checkstatus page"""
        return self.make_url(['manager', appid, 'apps', 'local', appid, 'setup'], _qs={
            'action': 'edit',
            'redirect_override': self.make_url(['manager', 'appinstall', appid, 'checkstatus'], translate=False, _qs={
                'state': state.serialize()
                })
            })

    def processAppUpload(self, f, force):
        """
        Process a file uploaded from the upload page
        """
        if not (isinstance(f, cgi.FieldStorage) and f.file):
            raise SBFileUploadException(_("No file was uploaded."))

        # Copy uploaded data to a named temporary file
        fd, tmpPath = tempfile.mkstemp()
        tfile = os.fdopen(fd, "w+")
        shutil.copyfileobj(f.file, tfile)
        tfile.flush() # leave the file open, but flush so it's all committed to disk

        try:
            args = { 'name': tmpPath, 'filename' : 1 }
            if force: 
                args['update'] = 1
            response, content = rest.simpleRequest('apps/local', postargs=args, sessionKey=cherrypy.session['sessionKey'])
            if response.status in (200, 201):
                atomFeed = rest.format.parseFeedDocument(content)
                return atomFeed[0].toPrimitive()['name']
            elif response.status == 409:
                raise SBFileUploadException(_("App with this name already exists."))
            raise SBFileUploadException(_("There was an error processing the upload."))
        except splunk.AuthorizationFailed:
            raise SBFileUploadException(_("Client is not authorized to upload apps."))
        finally:
			shutil.rmtree(tmpPath, True)
			


    def render_admin_template(self, *a, **kw):
        # use the AdminController's render_admin_template method for now
        # this won't be required once we remove modules from manager

        # get the manager controller
        manager = cherrypy.request.app.root.manager
        return manager.render_admin_template(*a, **kw)


    @route('/:appid')
    @expose_page(must_login=True)
    def start(self, appid, return_to=None, return_to_success=None, breadcrumbs=None, implicit_id_required=None, error=None, state=None, **kw):
        """
        The main entry point for installing or updating an app
        params:
        return_to - optional return address on completion
        return_to_success - optional return address used in favour or return_to if the app install is succesful
        breadcrumbs - pipe separated list of name|url tuples.  tuples themselves are joined by tabs.
        error - internally used error message
        state - internally used StateDict object
        """
        current_app = self.getLocalApp(appid)

        # state is a dict sublcass for storing things like the return_to url
        # that can be serialized to a URL-safe string by calling .serialize() on it
        # and restored by passing the raw data to StateDict.unserialize()
        if state:
            state = StateDict.unserialize(state)
            breadcrumbs = state['breadcrumbs']
        else:
            breadcrumbs = parse_breadcrumbs_string(breadcrumbs)
            breadcrumbs.append([_('Install app'), None])
            state = StateDict({
                'return_to': return_to if return_to else self.make_url(['manager', splunk.getDefault('namespace'), 'apps','local'], translate=False),
                'return_to_success': return_to_success,
                'breadcrumbs': breadcrumbs,
                'implicit_id_required': implicit_id_required
                })

        if current_app:
            # check whether a newer version is available
            if self.appUpgradeAvailable(current_app):
                state['implicit_id_required'] = current_app.get('update.implicit_id_required', None)
                return self.render_admin_template('/admin/appinstall/upgrade-available.html', {
                    'app': current_app,
                    'appid': appid,
                    'breadcrumbs': breadcrumbs,
                    'error': error,
                    'state': state
                })

            if self.isRestartRequired() or self.appNeedsSetup(current_app):
                # app is installed but hasn't been setup, or a restart is required
                return self.redirect_to_url(['/manager/appinstall', appid, 'checkstatus'], {
                    'state': state.serialize()
                    })

            # else the app is already installed and no upgrades are available
            return self.render_admin_template('/admin/appinstall/already-installed.html', {
                'app': current_app,
                'appid': appid,
                'state': state,
                'breadcrumbs': breadcrumbs
            })
                
        # see whether the app exists on Splunkbase (and thus whether Splunkbase is even reachable)
        try:
            remote_app = self.getRemoteAppEntry(appid)
        except splunk.ResourceNotFound:
            # app doesn't exist on splunkbase; allow for manual upload
            return self.render_admin_template('/admin/appinstall/app-not-found.html', {
                'appid': appid,
                'breadcrumbs': breadcrumbs,
                'state': state
            })
        except splunk.RESTException, e:
            if e.statusCode == 503:
                # splunkd will return 503 if it's configured not to contact splunkbase
                error = None
            else:
                # else something else went wrong
                error = str(e)
            return self.render_admin_template('/admin/appinstall/no-internet.html', {
                'appid': appid,
                'breadcrumbs': breadcrumbs,
                'state': state,
                'error': error
            })

        sbKey = self.getSBSessionKey()
        if sbKey:
            # user is already logged in, ready to go
            # display a template confirming that they really want to do the install
            return self.render_admin_template('/admin/appinstall/ready-to-install.html', {
                'appid': appid, 
                'appname': remote_app['appName'],
                'breadcrumbs': breadcrumbs,
                'error': error,
                'install_url': self.make_url(['/manager/appinstall', appid, 'install']),
                'state': state
            })

        # login required
        return self.render_admin_template('/admin/appinstall/sb-login.html', {
            'appid': appid,
            'breadcrumbs': breadcrumbs,
            'error': error,
            'state': state,
            'next': 'install'
        })

                
    @route('/:appid=_upload', methods=['GET', 'POST'])
    @expose_page(must_login=True)
    def upload(self, appid, return_to=None, breadcrumbs=None, state=None, appfile=None, force=None, **kw):
        """
        Present a form for direct upload of an app
        """
        if state:
            state = StateDict.unserialize(state)
            breadcrumbs = state.get('breadcrumbs')
        else:
            breadcrumbs = parse_breadcrumbs_string(breadcrumbs)
            breadcrumbs.append([_('Upload app'), None])
            state = StateDict({
                'return_to': return_to if return_to else self.make_url(['manager', splunk.getDefault('namespace'), 'apps','local'], translate=False),
                'breadcrumbs': breadcrumbs
                })
        error = None
        if appfile is not None and cherrypy.request.method == 'POST':
            try:
                force = (force == '1')
                appid = self.processAppUpload(appfile, force)
                module.moduleMapper.resetInstalledModules()
                memoizedViews.clearCachedViews()
                return self.checkstatus(appid, state=state)
            except SBFileUploadException, e:
                error = e.message
            except splunk.RESTException, e:
                error = e.get_extended_message_text()
            except cherrypy.HTTPRedirect, e:
                raise e
            except Exception,e:
                error = e.msg
            
                
        # display upload form
        return self.render_admin_template('/admin/appinstall/upload-app.html', {
            'appid': appid,
            'breadcrumbs': state.get('breadcrumbs'),
            'error': error,
            'state': state
        })


    @route('/:appid/:login=login', methods='POST')
    @expose_page(must_login=True)
    def login(self, appid, login, sbuser, sbpass, next, state, **kw):
        """
        Receive the Splunkbase login credentials from the login form and start the install
        """
        state = StateDict.unserialize(state)
        try:
            error = None
            sbSessionKey = None        
            sbSessionKey = self.splunkbaseLogin(sbuser, sbpass)
        except SBInvalidLoginException:
            error = _("Invalid username/password")
        except SBNotConnectedException:
            # let the user know that Splunkd either can't see the Internet or
            # has been configured not to talk to Splunkbase
            return self.render_admin_template('/admin/appinstall/no-internet.html', {
                'appid': appid,
                'breadcrumbs': state['breadcrumbs'],
                'state': state
            })

        if not sbSessionKey:
            return self.render_admin_template('/admin/appinstall/sb-login.html', {
                'appid': appid,
                'breadcrumbs': state['breadcrumbs'],
                'error': error,
                'state': state,
                'next': next
            })

        if next == 'install':
            return self.install(appid, state=state)
        return self.update(appid, state=state)


    @route('/:appid/:install=install', methods='POST')
    @expose_page(must_login=True)
    def install(self, appid, state, install=None, **kw):
        """
        Start the app download and installation processs
        """
        if not isinstance(state, StateDict):
            state = StateDict.unserialize(state)
        sbSessionKey = self.getSBSessionKey()
        if not sbSessionKey:
            logger.warn("Attempted install of app '%s' with sbSessionKey unset" % appid)
            return self.redirect_to_url(['/manager/appinstall/', appid], _qs={'error': _('SplunkApps login failed'), 'state': state.serialize()}) 

        # don't hold the session lock through network I/O
        cherrypy.session.release_lock()

        # attempt to actually install the app
        url = 'apps/remote/entriesbyid/%s' % appid
        requestArgs = {'action': 'install', 'auth': urllib.quote(sbSessionKey)}
        try:
            logger.info("Installing app %s" % appid)
            response, content = rest.simpleRequest(url, postargs=requestArgs, sessionKey=cherrypy.session['sessionKey'], timeout=APP_INSTALL_TIMEOUT)
        except splunk.AuthenticationFailed:
            # login expired
            return self.redirect_to_url(['/manager/appinstall', appid], _qs={'error': _('SplunkApps login timed out'), 'state': state.serialize()})
        except Exception, e:
            logger.exception(e)
            if e.statusCode == 403:
                return self.render_admin_template('/admin/appinstall/sb-login.html', {
                    'appid': appid,
                    'breadcrumbs': state['breadcrumbs'],
                    'error': _('SplunkApps login timed out'),
                    'state': state,
                    'next': install
                })
            else:
                return self.redirect_to_url(['/manager/appinstall', appid], _qs={'error': _('An error occurred while downloading the app: %s') % str(e), 'state': state.serialize()})

        if response.status not in [200, 201]:
            return self.redirect_to_url(['/manager/appinstall', appid], _qs={'error': _('An error occurred while installing the app: %s - %s') % (str(response.status), content), 'state': state.serialize()})

        module.moduleMapper.resetInstalledModules()
        memoizedViews.clearCachedViews()
        logger.info("App %s installed" % appid)
        return self.checkstatus(appid, state=state)


    @route('/:appid/:update=update', methods='POST')
    @expose_page(must_login=True)
    def update(self, appid, state, update=None, **kw):
        """
        Attempt to download and install an app update from Splunkbase
        """
        if not isinstance(state, StateDict):
            state = StateDict.unserialize(state)
        sbSessionKey = self.getSBSessionKey()
        if not sbSessionKey:
            # login required
            return self.render_admin_template('/admin/appinstall/sb-login.html', {
                'appid': appid,
                'breadcrumbs': state['breadcrumbs'],
                'state': state,
                'next': 'update'
            })
        url = 'apps/local/%s/update' % appid
        requestArgs = {
            'auth': urllib.quote(sbSessionKey),
            'implicit_id_required' : state.get('implicit_id_required')
        }
        try:
            logger.info("Updating app %s" % appid)
            response, content = rest.simpleRequest(url, postargs=requestArgs, sessionKey=cherrypy.session['sessionKey'])
        except splunk.AuthenticationFailed:
            # login expired
            return self.redirect_to_url(['/manager/appinstall', appid], _qs={'error': _('SplunkApps login timed out'), 'state': state.serialize()})
        except Exception, e:
            if e.statusCode == 403:
                logger.exception(e)
                return self.render_admin_template('/admin/appinstall/sb-login.html', {
                    'appid': appid,
                    'breadcrumbs': state['breadcrumbs'],
                    'error': _('SplunkApps login timed out'),
                    'state': state,
                    'next': update
                })
            else:
                return self.redirect_to_url(['/manager/appinstall', appid], _qs={'error': _('An error occurred while downloading the app: %s') % str(e), 'state': state.serialize()})

        if response.status not in [200, 201]:
            return self.redirect_to_url(['/manager/appinstall', appid], _qs={'error': _('An error occurred while installing the app: %s') % str(response.status,), 'state': state.serialize()})

        reset_app_build(appid)
        module.moduleMapper.resetInstalledModules()
        memoizedViews.clearCachedViews()
        logger.info("App %s installed" % appid)
        return self.checkstatus(appid, state=state)

    @route('/:appid/:enable=enable', methods='POST')
    @expose_page(must_login=True)
    def enable(self, appid, state=None, return_to=None, breadcrumbs=None, enable=None, **kw):
        """Enable a disabled app"""
        if state:
            state = StateDict.unserialize(state)
            breadcrumbs = state.get('breadcrumbs')
        else:
            state = StateDict({
                'return_to': return_to if return_to else self.make_url(['manager', splunk.getDefault('namespace'), 'apps','local'], translate=False),
                'breadcrumbs': breadcrumbs
                })
        entityURI = '/apps/local/'+appid+'/enable'
        en.controlEntity('enable', entityURI, sessionKey=cherrypy.session['sessionKey'])
        logger.info("App %s enabled" % appid)
        return self.checkstatus(appid, state=state)


    @route('/:appid/:checkstatus=checkstatus', methods=['POST', 'GET'])
    @expose_page(must_login=True)
    def checkstatus(self, appid, state=None, return_to=None, checkstatus=None, **kw):
        """
        Check the status of the installed app
        Is the app enabled?  If not prompt for that
        Is a restart required? If so prompt for that
        Does the app need to be setup? If so prompt for that
        Else set a message and bounce the user back to the return_url
        """
        if state:
            if not isinstance(state, StateDict):
                state = StateDict.unserialize(state)
        else:
            state = StateDict({
                'return_to': return_to if return_to else self.make_url(['manager', splunk.getDefault('namespace'), 'apps','local'], translate=False),
                })
        app = self.getLocalApp(appid)
        if not app:
            logger.warn("Attempted to access appinstall/checkstatus point for non-installed app %s" % appid)
            return self.redirect_to_url(['/manager/appinstall', appid], _qs={'state': state.serialize()})

        force = 0
        #if self.isRestartRequired() or True:
        if self.isRestartRequired() or force:
            # check the user has restart privileges
            serverControls = en.getEntities("server/control")
            restartLink = filter((lambda x: x[0] == 'restart'), serverControls.links)
            displayRestartButton = len(restartLink)>0
            return self.render_admin_template('/admin/appinstall/restart-required.html', {
                'displayRestartButton': displayRestartButton,
                'restart_target_url': self.make_url(['/manager/appinstall', appid, 'checkstatus'], _qs={'state': state.serialize()}),
                'breadcrumbs': state.get('breadcrumbs', []),
                'appid': appid,
                'state': state
            })
            
        # app is installed, does it need configuring?
        if self.appNeedsSetup(app):
            return self.render_admin_template('/admin/appinstall/setup-required.html', {
                'app': app,
                'state': state,
                'breadcrumbs': state.get('breadcrumbs', []),
                'setup_url': self.getSetupURL(appid, state)
            })

        if self.appIsDisabled(app):
            return self.render_admin_template('/admin/appinstall/enable-required.html', {
                'app': app,
                'appid': appid,
                'state': state,
                'breadcrumbs': state.get('breadcrumbs', [])
            })
            
        # else it's installed OK!
        try:
            msgid = MsgPoolMgr.get_poolmgr_instance()[UI_MSG_POOL].push('info', _('App "%(appname)s" was installed successfully') % {'appname': app.get('label', appid)})
        except KeyError:
            msgid = ''
        return_to = state.get('return_to')
        return_to_success = state.get('return_to_success')
        if return_to_success:
            # an explicit success-page url was supplied
            return_to_success = return_to_success.replace('__appid__', splunk.util.safeURLQuote(unicode(appid)))
            return self.redirect_to_url(return_to_success, _qs={'msgid': msgid})

        if return_to:
            # else use the default return to
            return self.redirect_to_url(return_to, _qs={'msgid': msgid})

        return self.redirect_to_url(['manager', splunk.getDefault('namespace'), 'apps','local'], _qs={'msgid': msgid})
        


