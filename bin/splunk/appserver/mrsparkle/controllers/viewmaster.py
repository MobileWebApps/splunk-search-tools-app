import cherrypy, json, math, re
from splunk.appserver.mrsparkle import *
import splunk.appserver.mrsparkle.lib.jsonresponse as jsonresponse
import splunk.util
import lxml.etree as et
import splunk.entity as en
from splunk.models.dashboard import Dashboard
from splunk.models.legacy_views import dashboard, form, panel

import logging
logger = logging.getLogger('splunk.appserver.controllers.viewmaster')


VIEW_ENTITY_CLASS = 'data/ui/views'

# define default number of panels to place in a row on dashboards
DEFAULT_DASHBOARD_ROW_SIZE = 2

CHART_DRILLDOWN_TYPES = [{
        "name": _("On"),
        "value": "all"
    },
    {
        "name": _("Off"),
        "value": "none"
    }]

TABLE_DRILLDOWN_TYPES = [{
        "name": _("Row"),
        "value": "row"
    },
    {
        "name": _("Cell"),
        "value": "all"
    },
    {
        "name": _("Off"),
        "value": "none"
    }]

class ViewmasterController(BaseController):
    '''
    Provides widget-based controls for view management
    '''
    
    # /////////////////////////////////////////////////////////////////////////
    #  Helpers
    # /////////////////////////////////////////////////////////////////////////

    def getViewObject(self, view_id, namespace, outputEntity=False):
        '''
        Returns a native ViewObject version of the requested view_id
        '''
        
        viewEntity = en.getEntity(VIEW_ENTITY_CLASS, view_id, namespace=namespace)
        
        parser = et.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
        root = et.XML(viewEntity[en.EAI_DATA_KEY], parser)

        if root.tag == 'dashboard':
            objectClass = dashboard.SimpleDashboard(isStorm=splunk.util.normalizeBoolean(cherrypy.config.get('storm_enabled')))
        elif root.tag == 'form':
            objectClass = form.SimpleForm()
        else:
            raise NotImplementedError, 'Cannot manage view object of type: %s' % root.tag

        objectClass.fromXml(root)
        
        if outputEntity:
            return objectClass, viewEntity
        else:
            return objectClass
        

    def viewObjectToXmlString(self, viewObject):
        '''
        Serializes a view object to XML string, ready to be committed to
        splunkd
        '''
        
        objectXml = viewObject.toXml()
        objectXml.insert(0, 
            et.Comment('\nNOTE: This file was automatically generated by Splunk.  Use caution when editing manually.\n')
        )
        return et.tostring(objectXml, xml_declaration=True, encoding='utf-8', pretty_print=True)
        
        
    def collatePanelOptions(self, formArgs):
        '''
        Collates raw panel option keys coming from HTTP POST into dict object
        suitable for insertion into Panel object mapper
        
        For example, an HTTP FORM input of:
            option.FOO 
        will be collated into the single container key:
            obj['options']['FOO']
        '''
        
        formArgs['options'] = {}
        for k in formArgs.keys():
            if k.startswith('option.'):
                formArgs['options'][k[7:]] = formArgs[k]
                del formArgs[k]
        
    # /////////////////////////////////////////////////////////////////////////
    #  view container management
    #
    #  These endpoints provide create/edit/delete functionality for the
    #  view objects, via the client-side viewmaster
    # /////////////////////////////////////////////////////////////////////////

    @route('/:namespace')
    @expose_page(methods=['GET','POST'])
    @set_cache_level('never')
    def createContainer(self, namespace, view_id='', view_label='', container_type='dashboard'):
        '''
        Handles dashboard creation
        
        GET /<namespace>
            ==> HTML template form to input create data
            
        POST /<namespace>
            ==> Saves the HTML input values from GET
            
            == returns JSON response
        '''

        #
        # serve template
        #
        
        if cherrypy.request.method == 'GET':
            return self.render_template('viewmaster/create_dashboard.html', {'namespace': namespace})
        
            
        #
        # handle create view
        #
        
        output = jsonresponse.JsonResponse()

        # clean inputs
        view_id = re.sub(r'[^\w]', '', view_id)
        view_label = view_label.strip() or view_id
        
        if view_id == '':
            output.success = False
            output.addError(_('Dashboard ID cannot be empty'))
            return self.render_json(output)
            
        # check that view doesn't already exist
        try:
            username = cherrypy.session['user'].get('name')
            dash_id = en.buildEndpoint(VIEW_ENTITY_CLASS, view_id, namespace=namespace, owner=username)
            Dashboard.get(dash_id)
            output.success = False
            output.addError(
                _('Cannot create new %(container_type)s: %(view_id)s already exists') \
                % {'container_type': container_type, 'view_id': view_id})
            return self.render_json(output)

        except splunk.ResourceNotFound:
            pass

        # generate new
        try:
            view = Dashboard(namespace, username, view_id)
            view.label = view_label
            view.save()

            output.data = {'view_id': view_id, 'view_label': view_label}
            output.addInfo(_('Successfully created new %(container_type)s: %(view_id)s') \
                % {'container_type': container_type, 'view_id': view_id})
            logger.info('Created new %s: namespace=%s id=%s label=%s' % (container_type, namespace, view_id, view_label))

        except Exception, e:
            logger.exception(e)
            output.success = False
            output.addError(_('Unable to create dashboard: %s') % e)

        return self.render_json(output)


    @route('/:namespace/:view_id', methods='GET')
    @expose_page(methods=['GET'], handle_api=True)
    @set_cache_level('never')
    def getContainer(self, namespace, view_id, mode='', **unused):
        '''
        Renders the dashboard edit page
        
        GET /<namespace>/<view_id>
            ==> HTML form page with dashboard edit form (labels, panels) and
                master panel edit form (hidden)
            
        GET /api/<namespace>/<view_id>
            ==> JSON structure of dashboard config (unused?)
        '''
        
        # serve data feed
        output = jsonresponse.JsonResponse()

        try:
            username = cherrypy.session['user'].get('name')
            dash_id = en.buildEndpoint(VIEW_ENTITY_CLASS, view_id, namespace=namespace, owner=username)
            dashObject = Dashboard.get(dash_id)
            output.data = dashObject._obj.toJsonable()

        except splunk.ResourceNotFound:
            cherrypy.response.status = 404
            output.success = False
            output.addError(_('View %s was not found') % view_id)
            return self.render_json(output)


        # serve template page
        if cherrypy.request.is_api:
            return self.render_json(output)
        else:
            cherrypy.response.headers['content-type'] = MIME_HTML

            # get supporting assets
            
            savedSearches = en.getEntities('saved/searches', 
                namespace=namespace, 
                count=-1, 
                search="is_visible=1")
            
            for savedSearch in savedSearches:
                acl = savedSearches[savedSearch]['eai:acl']
                if dashObject.metadata.sharing=='user':
                    continue
                if dashObject.metadata.sharing=='app' and acl['sharing']=='user':
                    savedSearches[savedSearch]['dq'] = True
                    continue
                if dashObject.metadata.sharing=='global' and acl['sharing']!='global':
                    savedSearches[savedSearch]['dq'] = True
                    continue
                if hasattr(dashObject.metadata.perms, 'read') and hasattr(acl['perms'], 'read'):
                    if dashObject.metadata.perms['read'].count('*')>0 and acl['perms']['read'].count('*')==0:
                        savedSearches[savedSearch]['dq'] = True
                        continue
                  
            #dashboardObject = splunk.entity.getEntity('data/ui/views', view_id, namespace=APP['id'], owner=cherrypy.session['user'].get('name'))
            #dashOwner = dashboardObject['eai:acl'].get('owner', 'nobody')

            editLink = self.make_url(
                ['manager', namespace, 'data/ui/views', view_id], 
                _qs=dict(
                    action='edit', 
                    url=self.make_url(['app', namespace, view_id]), 
                    redirect_override="/app/%s/%s" % (namespace, view_id)
                )
            )
            
            permissionsLink = self.make_url(
                ['manager', 'permissions', namespace, 'data/ui/views', view_id], 
                _qs=dict(
                    uri=en.buildEndpoint('data/ui/views', view_id, namespace=namespace, 
                    owner=dashObject.metadata.owner)
                )
            ) 

            return self.render_template('viewmaster/edit_dashboard.html', 
                {
                    'namespace': namespace,
                    'view_id': view_id,
                    'view_object': dashObject._obj,
                    'APP': {'id': namespace},
                    'savedSearches': savedSearches,
                    'editLink': editLink,
                    'permissionsLink': permissionsLink,
                    'mode': mode,
                })



    @route('/:namespace/:view_id', methods='POST')
    @expose_page(methods=['POST'])
    @set_cache_level('never')
    def setContainer(self, namespace, view_id, action, view_json=None):
        '''
        Provides support to modify dashboard configs
        
        POST /<namespace>/<view_id>
            &action=delete
                --> deletes the current view
            &action=edit
                --> updates the current view config (view JSON object)
                
            ==> returns a JSON response
        '''

        output = jsonresponse.JsonResponse()

        try:

            username = cherrypy.session['user'].get('name')
            dash_id = en.buildEndpoint(VIEW_ENTITY_CLASS, view_id, namespace=namespace, owner=username)
            dashObject = Dashboard.get(dash_id)

            if action == 'delete':
                dashObject.delete()
                output.addInfo(_('Successfully deleted %s') % view_id)

            elif action == 'edit':

                # convert incoming JSON to native struct; clean strings, 
                view_json = json.loads(view_json)

                if view_json.get('label'):
                    dashObject.label = view_json['label'].strip()
                if view_json.get('refresh'):
                    dashObject.refresh = int(view_json['refresh'].strip())
                    
                # handle panel reordering; wrap number of columns to the max
                # column constraint
                newPanelDefinition = []
                for row in view_json['new_panel_sequence']:
                    newRow = []
                    for seq in row:
                        newRow.append(dashObject._obj.getPanelBySequence(seq))
                        if len(newRow) >= splunk.models.dashboard.MAX_DASHBOARD_ROW_SIZE:
                            newPanelDefinition.append(newRow)
                            newRow = []
                    if len(row) > 0:
                        newPanelDefinition.append(newRow)
                dashObject._obj.rows = newPanelDefinition
                
                # ensure that the row grouping array is synced
                if len(dashObject._obj.rowGrouping) < len(dashObject._obj.rows):
                    dashObject._obj.rowGrouping.extend([None] * (len(dashObject._obj.rows) - len(dashObject._obj.rowGrouping)))

                # commit
                dashObject.save()
                output.addInfo(_('Successfully updated %s') % view_id)

            else:
                output.success = False
                output.addError(_('Unrecognized dashboard action: %s; cannot process') % action)
                logger.error('Unrecognized dashboard action: %s; cannot process' % action)

        except splunk.ResourceNotFound:
            cherrypy.response.status = 404
            output.addWarn(_('"%s" was not found; no action taken') % view_id)

        except Exception, e:
            output.success = False
            output.addError(_('Unable to update view %s: %s') % (view_id, e))
            logger.exception(e)

        return self.render_json(output)
                
        
    # /////////////////////////////////////////////////////////////////////////
    #  view container panel management
    #
    #  These endpoints provide create/edit/delete functionality for the
    #  panels contained in views; these are HTML generating
    # /////////////////////////////////////////////////////////////////////////

    @route('/:namespace/:view_id/:panel_type')
    @expose_page(methods=['POST'], handle_api=True)
    @set_cache_level('never')
    def createPanel(self, namespace, view_id, panel_type, panel_class, **panel_definition):
        '''
        Create a new panel to add to an existing dashboard
        
        POST /<namespace>/<view_id>/<panel_type=panel>
            &panel_class={table | chart | html | event | list}
            &<panel_property>=<property_value>
                --> creates a new panel
                
            the <panel_property> is a direct map to the panel XML data
            
            ==> returns a JSON response
        '''
        
        output = jsonresponse.JsonResponse()

        try:
            
            if panel_type != 'panel':
                raise ValueError, 'Only panel type "panel" is currently supported'
                
            # support all options
            self.collatePanelOptions(panel_definition)

            # get dashboard and create panel
            username = cherrypy.session['user'].get('name')
            dash_id = en.buildEndpoint(VIEW_ENTITY_CLASS, view_id, namespace=namespace, owner=username)
            dashObject = Dashboard.get(dash_id)

            dashObject.create_panel(
                type=panel_class,
                **panel_definition)

            dashObject.save()

        except Exception, e:
            logger.exception(e)
            output.success = False
            output.addError(_('Unable to add panel: %s') % e)
            
        return self.render_json(output)

    
    @route('/:namespace/:view_id/:panel_type/:panel_sequence', methods='GET')
    @expose_page(methods=['GET'], handle_api=True)
    @set_cache_level('never')
    def getPanel(self, namespace, view_id, panel_type, panel_sequence, **unused):
        '''
        Returns a dashboard panel config
        
        GET /<namespace>/<view_id>/panel/<panel_sequence>
            --> panel config for panel at <panel_sequence>
            
            ==> returns a JSON response
        '''
        
        output = jsonresponse.JsonResponse()

        try:
            username = cherrypy.session['user'].get('name')
            dash_id = en.buildEndpoint(VIEW_ENTITY_CLASS, view_id, namespace=namespace, owner=username)
            dashObject = Dashboard.get(dash_id)
            output.data = dashObject.get_panel(panel_sequence)

        except IndexError, e:
            cherrypy.response.status = 404
            output.success = False
            output.addError(_('Requested panel %s does not exist') % panel_sequence)
            
        except Exception, e:
            logger.exception(e)
            output.success = False
            output.addError(_('Unable to get panel at sequence %s: %s') % (panel_sequence, e))
        

        # serve the HTML fragment
        if not cherrypy.request.is_api:
            cherrypy.response.headers['content-type'] = MIME_HTML
            return self.render_template('viewmaster/edit_panel.html', 
                {
                    'namespace': namespace,
                    'view_id': view_id,
                    'view_object': dashObject._obj,
                    'panel_sequence': panel_sequence,
                    'chart_drilldown_types' : CHART_DRILLDOWN_TYPES,
                    'table_drilldown_types' : TABLE_DRILLDOWN_TYPES,
                    'APP': {'id': namespace}
                })

        # or just JSON representation
        else:
            return self.render_json(output)
        
        
        
    @route('/:namespace/:view_id/:panel_type/:panel_sequence', methods='POST')
    @expose_page(methods=['POST'], handle_api=True)
    @set_cache_level('never')
    def setPanel(self, namespace, view_id, panel_type, panel_sequence, panel_class=None, action='edit', **panel_definition):
        '''
        Provides management for view panel objects
        
        The HTTP signature for this method expects standard form params to match
        the property names used in the panel objects.  All form params are
        inserted into a dict and passed into the panel object for processing
        
        POST /<namespace>/<view_id>/panel/<panel_sequence>
            &action=edit
            --> updates the existing panel at <panel_sequence>
            &action=delete
            --> deletes the panel at <panel_sequence>
            
            ==> returns JSON response
        '''

        output = jsonresponse.JsonResponse()

        self.collatePanelOptions(panel_definition)

        try:
            username = cherrypy.session['user'].get('name')
            dash_id = en.buildEndpoint(VIEW_ENTITY_CLASS, view_id, namespace=namespace, owner=username)
            dashObject = Dashboard.get(dash_id)
        
            if action == 'edit':
                dashObject.set_panel(panel_sequence, panel_class, **panel_definition)
        
            elif action == 'delete':
                dashObject.delete_panel(panel_sequence)

            else:
                raise ValueError, 'Unknown action requested: %s' % action

            dashObject.save()
            output.addInfo(_('Successfully updated %s' % view_id))

        except Exception, e:
            logger.exception(e)
            output.success = False
            output.addError(_('Unable to update panel at sequence %s: %s') % (panel_sequence, e))

        return self.render_json(output)
        
