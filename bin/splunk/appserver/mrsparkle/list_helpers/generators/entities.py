import logging
import cherrypy
import splunk
from splunk import entity
from splunk.appserver.mrsparkle.list_helpers.generators import *

logger = logging.getLogger('splunk.appserver.mrsparkle.generators.entities')

class EntitiesListGenerator(ListGeneratorController):

    endpoint = 'entities'

    @route('/:one/:two/:three/:four', methods='GET')
    @expose_page(handle_api=True)
    @conditional_etag()
    @format_list_template()
    @normalize_list_params()
    def index(self, one, two, three=None, four=None, **kw):
        '''Returns a list of entities assuming the standard entity paths, omitting the /services path prefix.'''
        resp = []

        try:
            if 'owner' not in kw:
                kw['owner'] = cherrypy.session['user'].get('name')
            
            
            entity_path = '/'.join([seg for seg in [one, two, three, four] if seg is not None])
            entities = entity.getEntities(entity_path, sessionKey=cherrypy.session['sessionKey'], **entity.entityParams(**kw))
            
            # This is set to support pagination in non search result lists.
            # This same hack is used in JobManager, it should probably be removed by
            # implementing a standard non-job entity, like an EntityContext to compliment
            # the SearchContext. TODO: research this more.
            cherrypy.response.headers['X-Splunk-List-Length'] = entities.totalResults
            
        except (splunk.ResourceNotFound, splunk.RESTException), e:
            logger.warn('Splunk could not find entities at "%s".  Error message: %s' % (entity_path, str(e)))
            return resp
        
        for name, props in entities.items():
            app = {}
            app['name'] = name
            for key in props.properties:
                app[key] = props[key]
            resp.append(app)
        
        return resp
