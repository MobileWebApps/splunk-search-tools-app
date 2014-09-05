import cgi
import datetime
import json
import logging
import operator
import os
import tempfile
import time
import traceback

import cherrypy

import splunk, splunk.auth, splunk.util, splunk.entity, splunk.rest as rest
from splunk.appserver.mrsparkle import *
from splunk.appserver.mrsparkle.lib import jsonresponse, util, cached 
from splunk.appserver.mrsparkle.lib.eai import cpUnquoteEntity
from splunk.models.summarization import Summarization 
import splunk.clilib.cli_common as comm


from splunk.models.server_config import SplunkdConfig
import splunk.entity as en
import splunk.models.search_bar as SearchBar
from urllib import unquote

logger = logging.getLogger('splunk.appserver.controllers.summarization')
#logger.setLevel(logging.DEBUG)

# define default stack name
DEFAULT_STACK_NAME = 'enterprise'

# define set of license groups that allow pool creation
POOLABLE_GROUPS = ['Enterprise']

# define the model value for a pool's catch-all slave list
CATCHALL_SLAVE_LIST = ['*']



class SummarizationController(BaseController):
    """
    Summarization
    """

    #
    # attach common template args
    #

    def render_template(self, template_path, template_args = {}):
        template_args['appList'] = self.get_app_manifest()
        return super(SummarizationController, self).render_template(template_path, template_args)
    
    def is_normalized(self, hash):
        '''
        Returns whether the hash id is normalized or regular
        '''

        if hash[0] == 'N' and hash[1] == 'S':
            return True
        return False

    def get_app_manifest(self):
        '''
        Returns a dict of all available apps to current user
        '''
        
        output = cached.getEntities('apps/local', search=['disabled=false','visible=true'], count=-1)
                
        return output
 
    #
    # Summarization Dashboard
    #

    @route('/:selection')
    @expose_page(methods=['GET','POST'])
    def show_dashboard(self, ctrl=None, selection=None, ctrl_link=None, savedsearch=None, controller_exception=None, **kwargs):
        '''
        Summarization Dashboard 
        '''
        if cherrypy.config['is_free_license'] or cherrypy.config['is_forwarder_license']:
            return self.render_template('admin/402.html', {
                'feature'             : _('Report Acceleration Summaries')
            })
            
        logger.debug("\n\n\n tsum: In show_dashboard: \n\n\n") 

        # User is performing some action on a summary: removing, re-indexing, or verifying it
        if cherrypy.request.method == 'POST':
            logger.debug("post request!")
            try: 
                if ctrl == "remove" or ctrl == "redo": 
                    serverResponse, serverContent = rest.simpleRequest(ctrl_link, method='DELETE', raiseAllErrors=True)        
                    #logger.debug("serverResponse: %s" % serverResponse)
                    #logger.debug("serverContent: %s" % serverContent)
                if ctrl == "reschedule": 
                    serverResponse, serverContent = rest.simpleRequest(ctrl_link, method='POST', raiseAllErrors=True)        

                if serverResponse.status != 200: 
                    controller_exception = Exception('unhandled HTTP status=%s' % serverResponse.status)

                logger.debug("uri: %s, result of action: %s " % (ctrl_link, serverResponse))
            except splunk.InternalServerError, e:
                logger.debug("Error occurred: %s" % e)
                #TODO: This exception is not caught or handled in the summmarization dashboard html page 
                controller_exception = e
            
            # return a redirect so that when users reload the page they don't rerun their action    
            raise cherrypy.HTTPRedirect(self.make_url(['manager','system','summarization']), 302)

 
        entities = Summarization.all().filter_by_app('-').filter_by_user('-')
        if selection is not None:
            savedsearch = selection

        detailed_dashboard = False
        try:
            detailed_dashboard_str = comm.getConfKeyValue("limits", "auto_summarizer", "detailed_dashboard")
            if detailed_dashboard_str in ['true', '1', 't', 'y', 'yes']:
                detailed_dashboard = True
            logger.debug("detailed_dashboard = %s" % detailed_dashboard_str)
        except Exception, err:
            detailed_dashboard = False

        if savedsearch: 
            savedsearch = cpUnquoteEntity(savedsearch)
            tsumList = []
            for entity in entities: 
               for cursearch in entity.saved_searches.values(): 
                   if cursearch['name'] == savedsearch: 
                       tsumList.append(entity)
                       break 
        else:  
            logger.debug("kwargs: %s" % kwargs)
            ns = kwargs.get('ns', '-')
            pwnr = kwargs.get('pwnr', '-')
            kwargs['ns'] = ns
            kwargs['pwnr'] = pwnr

            tsumList = SearchBar.filterEntities(kwargs, entities)

        template_args = {
            'tsumList': tsumList,
            'selection' : unquote(selection) if selection else None,
            'controller_exception' : controller_exception,
            'isAutoExpand' : True if savedsearch else False, 
            'detailed_dashboard' : detailed_dashboard,
            'max_verify_time' : 15,
            'max_verify_buckets' : 100,
            'kwargs': kwargs,
        }

        return self.render_template('/summarization/dashboard.html', template_args)

    #
    # Verification Results Popup
    #

    @route('/:page=verify/:action=showResults')
    @expose_page(methods=['GET'])
    def verify_results_popup(self, isSuccess, result,  **kwargs):


        #TODO: don't hardcode the app as "search"
        template_args = {
            'app' : 'search',
            'isSuccess' : True if isSuccess == '1' else False, 
            'result' : result,
        }


        return self.render_template('/summarization/verification_result.html', template_args)




 
    #
    # Ajax calls are made to this function, which returns the statuses of all summaries
    #

    @route('/:page=allstatuses')
    @expose_page(methods=['GET'])
    def get_all_statuses(self, **kwargs):
        entities = Summarization.all().filter_by_app('-').filter_by_user('-')
        jsonStr = "["

        for entity in entities: 
            mod_time = util.timeToAgoStr(int(entity.mod_time)) if entity.mod_time else 'Never'
            isUpdatedALongTimeAgo = util.timeToAgoSeconds(int(entity.mod_time)) > 600
            convertedSize = int(entity.size)
            isNotStarted = len(entity.run_stats) == 0 and not entity.is_inprogress 
            isNotEnoughData = convertedSize == 0 and len(entity.run_stats) > 0 and len(entity.last_error) == 0
            jsonStr += '{"%s":{"complete":"%s", "mod_time":"%s", "is_suspended":"%s", "isNotEnoughData":"%s", "is_inprogress":"%s", "isNotStarted":"%s", "isUpdatedALongTimeAgo":"%s"}},' % (util.remove_special_chars(entity.id), entity.complete, mod_time, entity.is_suspended, isNotEnoughData, entity.is_inprogress, isNotStarted, isUpdatedALongTimeAgo)


        jsonStr = jsonStr[:-1]
        jsonStr += "]"
        return  jsonStr



 
    #
    # Ajax calls are made to this function, which returns the status of verification
    #

    @route('/:page=verifystatus')
    @expose_page(methods=['GET'])
    def get_verify_status(self, uri, **kwargs):
        entities = Summarization.all().filter_by_app('-').filter_by_user('-')

        normalized = False
        if uri is not None:
           underscore_pos = uri.rfind("_")
           if underscore_pos != -1 and (underscore_pos+2) < len(uri):
               if uri[underscore_pos+1] == 'N' and uri[underscore_pos+2] == 'S':
                   normalized = True

        if normalized:
            entities._additional_getargs = {}
            entities._additional_getargs["use_normalized"] = "true"
        else:
            entities._additional_getargs = {}
            entities._additional_getargs["use_normalized"] = "false"

        tsum = None
        for entity in entities: 
            if entity.id == uri:
                tsum = entity
                break

        verify_time = util.timeToAgoStr(int(tsum.verification_time)) if tsum.verification_time else 'Never' 

        jsonStr = '{"verification_state": "%s", "verification_buckets_failed":"%s", "verification_buckets_passed":"%s", "verification_buckets_skipped": "%s","verification_time":"%s", "verification_error": "%s"}' % (tsum.verification_state, tsum.verification_buckets_failed, tsum.verification_buckets_passed, tsum.verification_buckets_skipped, verify_time, tsum.verification_error)  

        return jsonStr



 
    #
    # Verification step 1
    #

    @route('/:page=verify/:step=step1/:action=new')
    @expose_page(methods=['GET'])
    def verify_step1_new(self, verifyLink, total_buckets, max_verify_time, max_verify_buckets, **kwargs):
        logger.debug("\n\n\n In verify_step1_new: \n\n\n") 

        controller_exception = None

        estimated_verify_time_fast = int(max_verify_time) * min(int(max_verify_buckets), int(total_buckets))  
        logger.debug("fast estimate: %s, max_verify_buckets: %s, total_buckets: %s" % (estimated_verify_time_fast, max_verify_buckets, total_buckets))
        estimated_verify_time_thorough = int(max_verify_time) * int(total_buckets)  


        #TODO: don't hardcode the app as "search"
        template_args = {
            'app' : 'search',
            'verifyLink': verifyLink,
            'total_buckets': total_buckets,
            'estimated_verify_time_fast' : estimated_verify_time_fast,
            'estimated_verify_time_thorough' : estimated_verify_time_thorough,
            'kwargs' : kwargs,
        }


        return self.render_template('/summarization/verify_step1.html', template_args)


    @route('/:page=verify/:step=step1/:action=create')
    @expose_page(must_login=True, trim_spaces=True, methods='POST')
    def verify_step1_create(self, verifyLink, mode, **kwargs):
        #logger.debug("\n\n\n In verify_step1_create: mode: %s\n\n\n" % mode) 

        controller_exception = []
        if mode == "fast":
            try: 
                postargs = {
                        'verify_delete' : True,
                        }

                serverResponse, serverContent = rest.simpleRequest(verifyLink, method='POST', postargs=postargs, raiseAllErrors=True)        

                if serverResponse.status != 200: 
                    controller_exception = Exception('unhandled HTTP status=%s' % serverResponse.status)

                logger.debug("uri: %s, result of action: %s " % (verifyLink, serverResponse))
            except splunk.InternalServerError, e:
                logger.debug("Error occurred: %s" % e)
                controller_exception.append(e)

        elif mode == "thorough": 
                try: 
                    postargs = {'max_verify_buckets' : 0, 
                        'max_verify_ratio' : 0.1, 
                        'max_verify_total_time' : 0, 
                        'max_verify_bucket_time' : 100,
                        'verify_delete' : True,
                        }

                    serverResponse, serverContent = rest.simpleRequest(verifyLink, method='POST', postargs=postargs, raiseAllErrors=True)        

                    if serverResponse.status != 200: 
                        controller_exception.append(Exception('unhandled HTTP status=%s' % serverResponse.status))

                    logger.debug("uri: %s, result of action: %s " % (verifyLink, serverResponse))
                except splunk.InternalServerError, e:
                    logger.debug("Error occurred: %s" % e)
                    controller_exception.append(e)
                except splunk.BadRequest, e:
                    logger.debug("Error occurred: %s" % e)
                    controller_exception.append(e)

        if len(controller_exception) == 0:  
            raise cherrypy.HTTPRedirect(self.make_url(['manager','system','summarization','verify','success']), 303)

        
        #TODO: don't hardcode the app as "search"
        template_args = {'verifyLink' : verifyLink, 
                         'controller_exception' : controller_exception, 
                         'app' : 'search',
                        }

        return self.render_template('/summarization/verify_step1.html', template_args)

 
    #
    #  Summary details page 
    #

    @route('/:page=details/:id')
    @expose_page(methods=['GET', 'POST'])
    def show_summary_details(self, id, uri, ctrl=None, ctrl_link=None,  **kwargs):

        normalized = self.is_normalized(id)

        controller_exception = None
        logger.debug("\n\n\nIn show_summary_details: uri: %s\n\n\n" % uri)

        # User is performing some action on a summary: removing, re-indexing, or verifying it
        if cherrypy.request.method == 'POST':
            logger.debug("post request!")
            try: 
                if ctrl == "redo": 
                    serverResponse, serverContent = rest.simpleRequest(ctrl_link, method='DELETE', raiseAllErrors=True)        
                if ctrl == "remove": 
                    serverResponse, serverContent = rest.simpleRequest(ctrl_link, method='DELETE', raiseAllErrors=True)        
                if ctrl == "reschedule": 
                    serverResponse, serverContent = rest.simpleRequest(ctrl_link, method='POST', raiseAllErrors=True)        

                if serverResponse.status != 200: 
                    controller_exception = Exception('unhandled HTTP status=%s' % serverResponse.status)

                logger.debug("uri: %s, result of action: %s " % (ctrl_link, serverResponse))
            except splunk.InternalServerError, e:
                logger.debug("Error occurred: %s" % e)
                #TODO: This exception is not caught or handled in the summmarization dashboard html page 
                controller_exception = e
            
            if not controller_exception: 
                # return a redirect so that when users reload the page they don't rerun their action    
                if ctrl == "remove": 
                    raise cherrypy.HTTPRedirect(self.make_url(['manager','system','summarization', ], ), 302)
                else: 
                    raise cherrypy.HTTPRedirect(self.make_url(['manager','system','summarization', 'details', id], _qs=(dict(uri=uri))), 302)


        entities = Summarization.all().filter_by_app('-').filter_by_user('-')
        if normalized:
            entities._additional_getargs = {}
            entities._additional_getargs["use_normalized"] = "true"
        else:
            entities._additional_getargs = {}
            entities._additional_getargs["use_normalized"] = "false"

        tsum = None
        for entity in entities: 
            if entity.id == uri:
                tsum = entity
                break

        if not tsum: 
            self.redirect_to_url(['manager', 'system', 'summarization'], 
                    _qs={
                        'controller_exception':'The report acceleration details could not be loaded for this summary'
                    }
                )
        
        
        convertedSize = int(tsum.size)
        isNotStarted = len(tsum.run_stats) == 0 and not tsum.is_inprogress 
        isNotEnoughData = convertedSize == 0  and len(tsum.run_stats) > 0 and len(tsum.last_error) == 0

        #TODO: don't hardcode the app as "search"
        template_args = {
            'controller_exception' : controller_exception,
            'tsum' : tsum,
            'normalized' : normalized,
            'kwargs' : kwargs,
            'isNotEnoughData' : isNotEnoughData,
            'isNotStarted' : isNotStarted,
        }


        return self.render_template('/summarization/summary_details.html', template_args)

 
    #
    # Verification step 2 (Customization)
    #

    @route('/:page=verify/:step=step2/:action=new')
    @expose_page(methods=['GET'])
    def verify_step2_new(self, verifyLink,total_buckets, **kwargs):

        logger.debug("\n\n\n In verify_step2_new: \n\n\n") 



        template_args = {
            'app' : 'search',
            'verifyLink': verifyLink,
            'total_buckets': total_buckets,
            'kwargs': kwargs,
            'controller"exception' : []
        }


        return self.render_template('/summarization/verify_step2.html', template_args)


    

    @route('/:page=verify/:step=step2/:action=create')
    @expose_page(must_login=True, trim_spaces=True, methods='POST')
    def verify_step2_create(self, verifyLink, **kwargs):

        controller_exception = []
        
        max_buckets = kwargs.get('max_buckets', '')
        max_time = kwargs.get('max_time', '')
        max_ratio = kwargs.get('max_ratio', '')
        auto_delete = kwargs.get('auto_delete', 'off')

        logger.debug("\n\n\n In verify_step2_create: max_buckets: %s, max_time: %s, max_ratio: %s, auto_delete: %s\n\n\n" % (max_buckets, max_time, max_ratio, auto_delete)) 

        # Validate parameters 
        try: 
            if not splunk.util.isValidUnsignedFloat(max_buckets):
                raise ValueError('"Max buckets"  must be a valid unsigned number') 
            if not splunk.util.isValidUnsignedFloat(max_ratio):
                raise ValueError('"Maximum verify ratio" must be a valid unsigned number') 
            if not splunk.util.isValidUnsignedFloat(max_time):
                raise ValueError('"Maximum verification time"  must be a valid unsigned number') 

            postargs = {'max_verify_buckets' : max_buckets, 
                        'max_verify_ratio' : '%04.2f' % float(max_ratio), 
                        'max_verify_total_time' : max_time, 
                        'verify_delete' : True if auto_delete == "on" else False,
                        }

           

            serverResponse, serverContent = rest.simpleRequest(verifyLink, method='POST', postargs=postargs, raiseAllErrors=True)        

            if serverResponse.status != 200: 
                controller_exception.append(Exception('unhandled HTTP status=%s' % serverResponse.status))

            logger.debug("uri: %s, result of action: %s " % (verifyLink, serverResponse))
        except splunk.InternalServerError, e:
            logger.debug("Error occurred: %s" % e)
            controller_exception.append(e)
            logger.debug("uri: %s, result of action: %s " % (verifyLink, serverResponse))
        except splunk.BadRequest, e:
            logger.debug("Error occurred: %s" % e)
            controller_exception.append(e)
        except ValueError, e:
            logger.debug("Error occurred: %s" % e)
            controller_exception.append(e)

        if len(controller_exception) == 0: 
            raise cherrypy.HTTPRedirect(self.make_url(['manager','system','summarization','verify','success']), 303)

        
        template_args = {'verifyLink' : verifyLink, 
                         'controller_exception' : controller_exception, 
                         'kwargs' : kwargs,
                         'app' : 'search'}

        return self.render_template('/summarization/verify_step2.html', template_args)



    
    @route('/:page=verify/:step=success')
    @expose_page(must_login=True, trim_spaces=True, methods='GET')
    def success(self, **params):
        #TODO: don't hardcode the app as "search"
        return self.render_template('/summarization/verification_success.html', dict(app="search"))
