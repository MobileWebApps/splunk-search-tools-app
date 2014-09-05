import cherrypy, json, logging, time
from splunk.appserver.mrsparkle import *
from splunk.appserver.mrsparkle.lib import util, config, i18n

logger = logging.getLogger('splunk.appserver.controllers.i18n_catalog')

class I18NCatalogController(BaseController):
    """/i18ncatalog"""

    #
    # exposed controllers
    #

    @route('/')
    @expose_page(must_login=False, methods='GET')
    def index(self, autoload=False):

        if autoload:
            cherrypy.response.headers['Content-type'] = MIME_JAVASCRIPT        
        else:
            cherrypy.response.headers['Content-type'] = splunk.appserver.mrsparkle.MIME_JSON
 
        # don't expose any data if user is not logged in
        if not cherrypy.session.get('sessionKey'):
            return ""

        # TODO: cache this data 

        time_begin = time.time()
        output = i18n.get_all_translations_cached(locale=None, autoload=autoload) # locale=None uses cherrypy current locale
        time_translations_retrieved = time.time()

        useBrowserCache = util.apply_etag(output)

        time_etag_calculated = time.time()

        logger.info("i18ncatalog: translations_retrieved=%s etag_calculated=%s overall=%s" % (
            time_translations_retrieved - time_begin,
            time_etag_calculated - time_translations_retrieved,
            time_etag_calculated - time_begin))

        if useBrowserCache:
            return None 

        return output

