import threading
import urllib

import cherrypy
from splunk.appserver.mrsparkle import *
from splunk.appserver.mrsparkle.lib import jsonresponse, startup, util, decorators, i18n
from splunk.models.user import User
import splunk, splunk.auth, splunk.util, splunk.entity, splunk.bundle
import logging, random, time

logger = logging.getLogger('splunk.appserver.controllers.account')

class AccountController(BaseController):
    """
    Handle logging in and logging out
    """

    # define filepath for successful login flag
    FLAG_FILE = util.make_splunkhome_path(['etc', '.ui_login'])

    # Store up to 100 credentials in memory during change password operations
    credential_cache = util.LRUDict(capacity=100)

    # The LRUDict is not thread safe; acquire a lock before operating with it
    credential_lock = threading.Lock()

    @expose_page(methods='GET')
    def index(self):
        return self.redirect_to_url('/')

    def updateCookieUID(self):
        """
        Creates and sets a long-lived cookie uid. If a uid cookie already exists it will not overwrite it.
        """
        if cherrypy.request.cookie.get('uid') is None:
            cherrypy.response.cookie['uid'] = splunk.util.uuid4().upper() # for consistency as splunkd returns uppercase guid
            cherrypy.response.cookie['uid']['expires'] = 5 * 365 * 24 * 3600

    def genCookieTest(self):
        """ Creates a random cval integer """
        return random.randint(0, 2**31)

    def cookieTest(self, cval):
        """ tests the given string and cval cookie value for type and value equality """
        try:
            return int(cherrypy.request.cookie['cval'].value) == int(cval)
        except:
            return False

    def updateCookieTest(self):
        """ set a cookie to check that cookies are enabled and pass the value to the form """
        cval = cherrypy.request.cookie.get('cval')
        if cval:
            try:
                cval = int(cval.value)
            except:
                cval = self.genCookieTest()
        else:
            cval = self.genCookieTest()
        cherrypy.response.cookie['cval'] = cval
        return cval

    def handleStormLogin(self, return_to=None, **kwargs):
        from splunk.appserver.mrsparkle.lib import storm
        cherrypy.session.regenerate()
        if cherrypy.request.method == 'POST' and kwargs.has_key('storm_token'):
            ts, token = storm.decrypt_token(kwargs['storm_token'])
            max_token_age = cherrypy.config.get('storm_max_token_age', 3600)
            if ts + max_token_age < time.time():
                logger.warn("Storm session token has expired")
                token = defaults = None
            else:
                logger.info("Got storm token OK")
                cherrypy.session['storm_token'] = token
                new_session = True
                attempts = 2
                ok = False
                while attempts:
                    attempts -= 1
                    defaults = storm.get_storm_defaults(new_session)
                    if not defaults:
                        continue
                    if splunk.auth.ping(sessionKey=defaults['sessionKey']):
                        ok = True
                        break
                if not defaults or not ok:
                    if not defaults:
                        logger.error("Failed to fetch user's default settings from Storm")
                    else:
                        logger.error("Storm issued a token with an invalid session key %s" % defaults['sessionKey'])
                    token = defaults = None
                    cherrypy.session['storm_token'] = None
        else:
            defaults = storm.get_storm_defaults()
        if not defaults:
            url =  cherrypy.config.get('storm_user_url')
            if not url:
                storm_host = cherrypy.config.get('storm_host', '127.0.0.1')
                storm_port = cherrypy.config.get('storm_port', 80)
                if cherrypy.config['storm_port'] != 80:
                    url = "http://%s:%s/" % (storm_host, storm_port)
                else:
                    url = "http://%s/" % (storm_host)
            if return_to:
                return_quoted = urllib.quote_plus(return_to)
                url += "?return_to_splunkweb=" + return_quoted
            logger.warn("action=storm_login_failed, redirect_url=%s, "
                        "storm_token_set=%s", url,
                        kwargs.has_key('storm_token'))
            raise cherrypy.HTTPRedirect(url)
        cherrypy.session['user'] = {
            'name': defaults['user'],
            'fullName': 'Storm User',
            'id': 1
        }
        cherrypy.session['sessionKey'] = defaults['sessionKey']

        if return_to:
            # return_to could potentially have a query string and a fragment, and hence break in IE6
            # since we're bypassing self.redirect_to_url, we have to check for that
            if util.is_ie_6() and not util.redirect_url_is_ie_6_safe(return_to):
                return self.client_side_redirect(util.make_url_internal(return_to))
            raise cherrypy.HTTPRedirect(util.make_url_internal(return_to))
        else:
            return self.redirect_to_url('/')


    def getUpdateCheckerBaseURL(self):
        # validate the checker URI
        updateCheckerBaseURL = str(cherrypy.config.get('updateCheckerBaseURL', '')).strip()
        if not any(map(updateCheckerBaseURL.startswith, ['http://', 'https://'])):
            updateCheckerBaseURL = None
        return updateCheckerBaseURL

    def getLoginTemplateArgs(self, return_to=None, session_expired_pw_change=False):
        """Generate the base template arguments for account/login.html"""
        ref = cherrypy.request.headers.get('Referer')

        # free license doesn't really expire; we just push the nagware here
        if cherrypy.config.get('is_free_license'):
            session_expired = False
        else:
            session_expired = ref and ref.startswith(cherrypy.request.base) and not ref.endswith(cherrypy.request.path_info)

        templateArgs = {
            'return_to' : return_to,
            'session_expired': session_expired,
            'session_expired_pw_change': session_expired_pw_change,
            'updateCheckerBaseURL': self.getUpdateCheckerBaseURL(),
            'serverInfo': self.getServerInfo(),
            'isAutoComplete': self.isAutoComplete(),
            'bad_cookies': False,
            'cval': self.updateCookieTest(),
            'loginContent': cherrypy.config.get('login_content', ''),
            'hasLoggedIn': True
        }

        return templateArgs


    @expose_page(must_login=False, methods=['GET','POST'], verify_session=False)
    @lock_session
    @set_cache_level('never')
    def login(self, username=None, password=None, return_to=None, cval=None, newpassword=None, **kwargs):

        # Force a refresh of startup info so that we know to
        # redirect if license stuff has expired.
        startup.initVersionInfo(force=True)

        updateCheckerBaseURL = self.getUpdateCheckerBaseURL()

        # set a long lived uid cookie
        self.updateCookieUID()

        templateArgs = self.getLoginTemplateArgs(return_to=return_to)

        if not return_to:
            return_to = '/'
        if return_to[0] != '/':
            return_to = '/' + return_to

        #dont allow new login if session established.
        if cherrypy.session.get('sessionKey') and return_to:
            raise cherrypy.HTTPRedirect(util.make_url_internal(return_to))

        # Storm
        if cherrypy.config.get('storm_enabled'):
            return self.handleStormLogin(return_to=return_to, **kwargs)

        #
        # GET
        #
        if cherrypy.request.method == 'GET' and newpassword is None:

            # free license will auth on anything so statically seed
            if cherrypy.config.get('is_free_license'):

                # Start with a clean and minty fresh session
                cherrypy.session.regenerate()

                cherrypy.session['user'] = {
                    'name': 'admin',
                    'fullName': 'Administrator',
                    'id': 1
                }
                sessionKey = splunk.auth.getSessionKey("admin", "freeneedsnopassword", hostPath=self.splunkd_urlhost)
                cherrypy.session['sessionKey'] = sessionKey

                if not updateCheckerBaseURL:
                    return self.redirect_to_url('/app/%s' % splunk.getDefault('namespace'))


            # check for previously successful login
            templateArgs['hasLoggedIn'] = self.hasLoggedIn()

            if templateArgs['return_to'] is None and cherrypy.config.get('root_endpoint') not in ['/', None, '']:
                templateArgs['return_to'] = util.make_url_internal(cherrypy.config.get('root_endpoint'))

            # otherwise, show page
            return self.render_template('account/login.html', templateArgs)

        #
        # POST
        #

        # Check that the cookie we set when the login page was loaded has made it to us intact
        if 'cval' not in cherrypy.request.cookie or not self.cookieTest(cval):
            templateArgs['bad_cookies'] = 1
            return self.render_template('account/login.html', templateArgs)

        ua = cherrypy.request.headers.get('user-agent', 'unknown')
        ip = cherrypy.request.remote.ip
        
        if username:
            username = username.strip().lower()
        
        try:
            sessionKey = splunk.auth.getSessionKey(username, password, hostPath=self.splunkd_urlhost, newPassword=newpassword)
        except splunk.AuthenticationFailed, e:
            logger.error('user=%s action=login status=failure ' \
                         'reason=user-initiated useragent="%s" clientip=%s ERROR=%s'
                         % (username, ua, ip, str(e.msg)))

            templateArgs['invalid_password'] = 1

            forced_password_change = str(e.msg).count('fpc')
            forced_password_message = str(e.extendedMessages)

            if forced_password_change:
                templateArgs['fpc'] = True
                # cache current credentials in memory only
                credentials = {'username': username, 'password': password}
                with AccountController.credential_lock:
                    AccountController.credential_cache[cherrypy.session.id] = credentials
                cherrypy.session['cval'] = cval
                cherrypy.session['fpc'] = True  # forced password change

                templateArgs['err'] = _(forced_password_message)
                logger.info('user=%s action=login status=%s' % (username, forced_password_message))
                
                return self.render_template('account/passwordchange.html', templateArgs)
            else:
                return self.render_template('account/login.html', templateArgs)

        en = splunk.entity.getEntity('authentication/users', username, sessionKey=sessionKey)
        fullName = username
        if en and 'realname' in en and en['realname']:
            fullName = en['realname']

        # Start with a clean and minty fresh session
        cherrypy.session.regenerate()
        cherrypy.session['sessionKey'] = sessionKey
        # TODO: get rest of user info
        cherrypy.session['user'] = {
            'name': username,
            'fullName': fullName,
            'id': -1
        }

        # Log user login
        logger.info('user=%s action=login status=success session=%s ' \
                    'reason=user-initiated useragent="%s" clientip=%s'
                % (username, sessionKey, ua, ip))

        # Stash the remote user if splunkd is in SSO mode.  Note we do not stash the user if the
        # incoming request IP does not match any of the IP addresses in the list of trusted IPs.
        # This allows users to still login via SSO, logout, and login as another user
        # but ensures that if they logout of SSO, they will be logged out of Splunk.
        if util.in_sso_mode():
            incoming_request_ip = cherrypy.request.remote.ip
            splunkweb_trusted_ip = splunk.util.stringToFieldList(cherrypy.config.get(decorators.SPLUNKWEB_TRUSTED_IP_CFG))
            if incoming_request_ip in splunkweb_trusted_ip:
                remote_user_header = cherrypy.request.config.get(decorators.SPLUNKWEB_REMOTE_USER_CFG) or decorators.DEFAULT_REMOTE_USER_HEADER
                cherrypy.session[decorators.REMOTE_USER_SESSION_KEY] = cherrypy.request.headers.get(remote_user_header)

        # Check for an expired license and override any action if one is present
        if cherrypy.config['license_state'] == 'EXPIRED':
            templateArgs['return_to'] = '/licensing'

        # If this is the first time admin has logged in, suggest changing the password
        if not self.hasLoggedIn() and username == 'admin':
            self.setLoginFlag(True)
            templateArgs = {}
            templateArgs['return_to'] = return_to
            templateArgs['cpSessionKey'] = cherrypy.session.id
            return self.render_template('account/passwordchange.html', templateArgs)

        if return_to:
            # return_to could potentially have a query string and a fragment, and hence break in IE6
            # since we're bypassing self.redirect_to_url, we have to check for that
            if util.is_ie_6() and not util.redirect_url_is_ie_6_safe(return_to):
                return self.client_side_redirect(util.make_url_internal(return_to))

            # We need to redirect to the return_to page, but we also need to return
            # the new CSRF cookie. We do this by creating the redirect but not 
            # raising it as an exception. Instead, we use set_response (which
            # you can read about here: http://docs.cherrypy.org/dev/refman/_cperror.html#functions),
            # which will set it on the cherrypy.response object.
            # Finally, we also do not return any content, since there is none
            # to return (as it is a redirect).
            redirect_response = cherrypy.HTTPRedirect(util.make_url_internal(return_to))
            redirect_response.set_response()
            util.setFormKeyCookie()
            
            return

        return self.redirect_to_url('/')

    @expose_page(must_login=False, methods=['GET'], verify_session=False)
    def sso_error(self, **kw):
        '''
        Called to tell user that SSO login worked, but no splunk user exists.
        '''
        if not util.in_sso_mode():
            raise cherrypy.HTTPError(404)
        return self.render_template('account/sso_error.html')

    @expose_page(must_login=False, verify_session=False, methods=['POST'])
    @lock_session
    def passwordchange(self, newpassword=None, confirmpassword=None, return_to=None, cval=None, **kw):
        '''
        Suggest admin to change the password on first time run 
        And force flagged users to change their passwords before they continue
        '''
        # We set must_login to False in the expose_page decoator so we can perform the checks here instead
        # and give the user a more useful message if the session has expired leaving the password unchanged
        # but first we check if the passwords pass
        
        err = None
        templateArgs = {
            'err' : err,
            'return_to' : return_to,
            'cpSessionKey' : cherrypy.session.id
        }

        if 'fpc' in cherrypy.session:
            templateArgs['fpc'] = True

        if not newpassword or len(newpassword) == 0:
            templateArgs['err'] = _("Empty passwords are not allowed.")
            return self.render_template('account/passwordchange.html', templateArgs)

        if newpassword != confirmpassword:
            templateArgs['err'] = _("Passwords didn't match, please try again.")
            return self.render_template('account/passwordchange.html', templateArgs)

        if newpassword == 'changeme':
            templateArgs['err'] = _("For security reasons, the new password must be different from the default one.")
            return self.render_template('account/passwordchange.html', templateArgs)

        # Forced Password Change workflow is checked before the session check b/c user isn't authenticated yet
        if 'fpc' in cherrypy.session:        
            try:
                # Fetch the user's verified cached credentials from when they originally attempted to login
                with AccountController.credential_lock:
                    # Will raise a KeyError if the credentials have expired from the LRU or CP was restarted
                    credentials = AccountController.credential_cache[cherrypy.session.id]

                if newpassword == credentials['password']:
                    templateArgs['err'] = _("For security reasons, the new password must be different from the previous one.")
                    return self.render_template('account/passwordchange.html', templateArgs)

                # Will be resetup, if required, by self.login()
                del cherrypy.session['fpc']
                with AccountController.credential_lock:
                    try:
                        del AccountController.credential_cache[cherrypy.session.id]
                    except KeyError:
                        pass

                # Fake a login form submission; this call must return as soon as the call to login() completes!
                return self.login(username=credentials['username'], password=credentials['password'],
                                  newpassword=newpassword, return_to=return_to, cval=cherrypy.session['cval'])

            except (splunk.AuthenticationFailed, KeyError):
                cherrypy.session.delete()
                self.setLoginFlag(False)
                templateArgs = self.getLoginTemplateArgs(return_to=return_to, session_expired_pw_change=True)
                return self.render_template('account/login.html', templateArgs)

        if not cherrypy.session.get('sessionKey', None) or not util.isValidFormKey(kw['splunk_form_key']):
            # The user intended to change the password; reset the flag so this page will be shown again
            cherrypy.session.delete()
            self.setLoginFlag(False)
            templateArgs = self.getLoginTemplateArgs(return_to=return_to, session_expired_pw_change=True)
            return self.render_template('account/login.html', templateArgs)

        try:
            user = User.get(cherrypy.session['user']['name'])
            user.password = newpassword
            if not user.save():
                logger.error('Unable to save new admin password.')

        except splunk.AuthenticationFailed:
            cherrypy.session.delete()
            self.setLoginFlag(False)
            templateArgs = self.getLoginTemplateArgs(return_to=return_to, session_expired_pw_change=True)
            return self.render_template('account/login.html', templateArgs)

        except splunk.RESTException, e:
            err = e.get_message_text()
            if ':' in err:
                err = err[err.find(':')+2:]

            logger.error("Failed to change the password: %s." % err)
            templateArgs['err'] = err
            return self.render_template('account/passwordchange.html', templateArgs)

        if return_to and return_to[0]=='/':
            try:
                return self.redirect_to_url(util.make_url_internal(return_to), translate=False)
            except util.InvalidURLException:
                # invalid character in the URL supplied; fall through and redirect to / instead
                logger.warn("Invalid return_to URL passed to login page")
                pass

        return self.redirect_to_url('/')

    @expose_page(must_login=False, methods='GET')
    @lock_session
    def insecurelogin(self, username=None, password=None, return_to=None):
        '''
        Provide insecure login endpoint for HTTP GET-based credential passing
        '''

        # Force a refresh of startup info so that we know to
        # redirect if license stuff has expired.
        startup.initVersionInfo(force=True)

        output = jsonresponse.JsonResponse()

        if not splunk.util.normalizeBoolean(cherrypy.config.get('enable_insecure_login')):
            cherrypy.response.status = 403
            output.success = False
            output.addError('The insecure login endpoint is disabled. See web.conf for details.')
            return self.render_json(output)

        if not username or not password:
            cherrypy.response.status = 400
            output.success = False
            output.addError('Missing credentials')
            return self.render_json(output)

        ua = cherrypy.request.headers.get('user-agent', 'unknown')
        ip = cherrypy.request.remote.ip
        try:
            sessionKey = splunk.auth.getSessionKey(username, password, hostPath=self.splunkd_urlhost)
        except Exception, e:
            logger.error('user=%s action=insecurelogin status=failure session=%s ' \
                'reason=user-initiated useragent="%s" clientip=%s'
                % (username, sessionKey, ua, ip))
            output.parseRESTException(e)
            output.success = False
            return self.render_json(output)

        # Log user login
        logger.info('user=%s action=insecurelogin status=success session=%s ' \
                    'reason=user-initiated useragent="%s" clientip=%s'
                    % (username, sessionKey, ua, ip))

        en = splunk.entity.getEntity('authentication/users', username, sessionKey=sessionKey)
        fullName = username
        if en and 'realname' in en and en['realname']:
            fullName = en['realname']

        # Start with a clean and minty fresh session
        cherrypy.session.regenerate()
        cherrypy.session['sessionKey'] = sessionKey

        # TODO: get rest of user info
        cherrypy.session['user'] = {
            'name': username,
            'fullName': fullName,
            'id': -1
        }

        # Stash the remote user if splunkd is in SSO mode.  Note we do not stash the user if the
        # incoming request IP does not match any of the IP addresses in the list of trusted IPs.
        # This allows users to still login via SSO, logout, and login as another user
        # but ensures that if they logout of SSO, they will be logged out of Splunk.
        if util.in_sso_mode():
            incoming_request_ip = cherrypy.request.remote.ip
            splunkweb_trusted_ip = splunk.util.stringToFieldList(cherrypy.config.get(decorators.SPLUNKWEB_TRUSTED_IP_CFG))
            if incoming_request_ip in splunkweb_trusted_ip:
                remote_user_header = cherrypy.request.config.get(decorators.SPLUNKWEB_REMOTE_USER_CFG) or decorators.DEFAULT_REMOTE_USER_HEADER
                cherrypy.session[decorators.REMOTE_USER_SESSION_KEY] = cherrypy.request.headers.get(remote_user_header)

        # Check for an expired license and override any action if one is present
        if cherrypy.config['license_state'] == 'EXPIRED':
            return self.redirect_to_url('/licensing')

        if return_to:
            return self.redirect_to_url(util.make_url_internal(return_to), translate=False)

        return self.redirect_to_url('/')



    @expose_page(must_login=False, methods='GET')
    @lock_session
    def logout(self):

        # Force a refresh of startup info so that we know to
        # redirect if license stuff has expired.
        startup.initVersionInfo(force=True)

        # Log to file
        try:
            username = cherrypy.session['user']['name']
            session = cherrypy.session['sessionKey']
            ip = cherrypy.request.remote.ip
            ua = cherrypy.request.headers.get('user-agent', 'unknown')
            logger.info('user=%s action=logout status=success ' \
                'reason=user-initiated useragent="%s" clientip=%s session=%s'
                % (username, ua, ip, session))
        except (KeyError, AttributeError), e:
            # User wasn't logged in, or no session
            pass


        templateArgs = {
            'return_to' : None,
            'logged_out' : 1,
            'updateCheckerBaseURL': None,
            'serverInfo': self.getServerInfo(),
            'isAutoComplete': self.isAutoComplete(),
            'cval' : self.updateCookieTest(),
            'loginContent': cherrypy.config.get('login_content', ''),
            'hasLoggedIn': True
        }

        if templateArgs['return_to'] is None and cherrypy.config.get('root_endpoint') not in ['/', None, '']:
            templateArgs['return_to'] = util.make_url_internal(cherrypy.config.get('root_endpoint')) 
        
        cherrypy.session.delete()

        # if free version times out and kicks to logout screen
        # just forward to root to get the nagware
        if cherrypy.config.get('is_free_license'):
            return self.redirect_to_url('/')

        return self.render_template('account/login.html', templateArgs )


    def isAutoComplete(self):
        return splunk.util.normalizeBoolean(cherrypy.config.get('enable_autocomplete_login', True))


    def getServerInfo(self):
        '''
        Retrieve a python dictionary of the /services/server/info endpoint.
        '''

        output = {}
        for k in ['build_number', 'cpu_arch', 'version_label', 'is_free_license', 'is_trial_license', 'license_state', 'os_name', 'guid', 'master_guid', 'license_desc', 'install_type', 'django', 'addOns', 'activeLicenseGroup']:
            output[k] = cherrypy.config.get(k)
        return output


    def setLoginFlag(self, setFlag=None):
        '''
        Persists a flag (via an empty file) that indicates if someone has
        successfully logged into the system before
        '''

        flagged = os.path.isfile(self.FLAG_FILE)

        try:
            if not flagged and setFlag:
                f = open(self.FLAG_FILE, 'w')
                f.close()
                logger.info('setting successful login flag to: true')
            elif flagged and not setFlag:
                os.remove(self.FLAG_FILE)
                logger.info('setting successful login flag to: false')

        except Exception, e:
            logger.error('Unable to set the login flag')
            logger.exception(e)

    
    def hasLoggedIn(self):
        '''
        Indicates if someone has logged into this system before.
        '''
        return os.path.isfile(self.FLAG_FILE)


