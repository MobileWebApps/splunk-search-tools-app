from urlparse import urlparse 
import sys
import lxml.etree as et
import logging
import urllib
import time
import json
import copy

import splunk
import splunk.rest as rest
import splunk.entity as entity
import splunk.auth
import splunk.models.dashboard as sm_dashboard
import splunk.models.dashboard_panel as sm_dashboard_panel
import splunk.models.saved_search as sm_saved_search
import splunk.search
import splunk.search.Parser as Parser
from splunk.util import normalizeBoolean
import pdfgen_utils as pu

logger = pu.getLogger()

class AbstractViewType(object):
    # data describing associated search and search job
    _searchParams = {}
    _searchJobObj = None
    isRealtime = False
    _ownDispatch = False # set to True if this view 'owns' the dispatch of its search
    _viewStateDict = None
    _namespace = None
    _owner = None
    _sessionKey = None

    def setSearchParams(self, searchParams):
        self._searchParams = searchParams

    def getSearchParams(self):
        return self._searchParams

    def dispatchSearch(self, overrideNowTime=None, maxRowsPerTable=None):
        """ dispatch the view's search, returns true if successful """
        searchJobObj = None
        searchCommand = None
        search = self.getSearchParams()

        if not pu.SP_MODE in search or not pu.SP_COMMAND in search:
            self.setSearchJobObj(None) 
            return False

        logger.debug("dispatchSearch search mode=%s, command=%s, isRealtime=%s, overrideNowTime=%s" % (str(search[pu.SP_MODE]), str(search[pu.SP_COMMAND]), str(self.isRealtime), overrideNowTime))

        if search[pu.SP_MODE] == 'saved':
            # dispatch the job using the saved search dispatch endpoint

            searchName = search[pu.SP_COMMAND]
            try:
                searchJobObj, ownDispatch = pu.dispatchSavedSearch(searchName, namespace=self._namespace, owner=self._owner, sessionKey=self._sessionKey, forceHistoricSearch=True, overrideNowTime=overrideNowTime)
                # since we forced the historic search, make sure that self.isRealtime indicates that
                self.isRealtime = False
                self._ownDispatch = ownDispatch 
            except splunk.QuotaExceededException as e:
                logger.error("dispatchSearch exception dispatching saved search, " + searchName + ": " + str(e))
            except splunk.SearchException as e:
                logger.error("dispatchSearch exception dispatching saved search, " + searchName + ": " + str(e))

        else:
            searchCommand = search[pu.SP_COMMAND]

            options = {}

            # perf improvements for event listing
            views = self.getRenderTypes()
            if maxRowsPerTable and all(view == 'event' for view in views):
                options['maxEvents'] = maxRowsPerTable
            
            if search[pu.SP_EARLIEST_TIME] != None:
                options['earliestTime'] = search[pu.SP_EARLIEST_TIME].replace(u'rt',u'')
            if search[pu.SP_LATEST_TIME] != None:
                options['latestTime']   = search[pu.SP_LATEST_TIME].replace(u'rt',u'')
            if overrideNowTime != None:
                options['now'] = int(overrideNowTime)
            self.isRealtime = False # we just made sure that the search isn't realtime      
 
            try:
                searchJobObj = splunk.search.dispatch(pu.prepareInlineSearchCommand(searchCommand), sessionKey=self._sessionKey, **options)
                self._ownDispatch = True
            except splunk.QuotaExceededException as e:
                logger.error("dispatchSearch exception dispatching string search, [" + searchCommand + "]: " + str(e))
            except splunk.SearchException as e:
                logger.error("dispatchSearch exception dispatching string search, [" + searchCommand + "]: " + str(e))

        self.setSearchJobObj(searchJobObj)
        return searchJobObj != None

    def getViewIndex(self):
        """ return the view index, for reports, always return 0, for dashboard panels,
            return the sequence number """
        return 0

    def requiresSearchJobObj(self):
        nonSearchRenderTypes = ['html']   

        types = self.getRenderTypes()
        logger.debug("requiresSearchJobObj types = %s, nonSearchRenderTypes = %s" % (types, nonSearchRenderTypes))

        for type in types:
            if type in nonSearchRenderTypes:
                continue
            return True
        return False 

    def setSearchJobObj(self, searchJobObj):
        self._searchJobObj = searchJobObj

    def getSearchJobObj(self):
        return self._searchJobObj

    def getSearchJobResults(self):
        if self.isRealtime:
            return self._searchJobObj.results_preview
        else:
            return self._searchJobObj.results

    def getSearchJobFeed(self, feedCount = None):

        feedArgs = {}
        if feedCount != None:
            feedArgs['count'] = feedCount
        if self.isRealtime:
            return self._searchJobObj.getFeed(mode='results_preview', **feedArgs)
        else:
            return self._searchJobObj.getFeed(mode='results', **feedArgs)

    def getSearchJobEvents(self):
        if self.isRealtime:
            # don't return .events here due to
            # ResultSet.__iter__ sleeps if not mode=results_preview
            return self._searchJobObj.results_preview
        else:
            return self._searchJobObj.events

    def isSearchComplete(self):
        return self._searchJobObj != None and self._searchJobObj.isDone

    def touchSearchJob(self):
        # if we don't have a _searchJobObj OR we cannot write to the _searchJobObj then we shouldn't try to touch it.
        if ((self._searchJobObj == None) or not self._searchJobObj.eaiacl or (self._searchJobObj.eaiacl.get('can_write') == '0')):
            return
        self._searchJobObj.touch()

    def cancelSearch(self):
        if self._searchJobObj != None and self._ownDispatch == True:
            logger.info("PDF view canceled. canceling search job: %s" % self._searchJobObj.sid)
            self._searchJobObj.cancel() 

    def getRenderTypes(self):
        """ returns array of types
            type: 'chart', 'table', 'events', 'map', 'single'
        """
        return []

    def getRenderParams(self):
        return {}

    def getChartProps(self):
        props = {}

        if self._viewStateDict != None:
            props.update(pu.mapViewStatePropsToJSChartProps(self._viewStateDict))        
            
        return props

    def getMapProps(self):
        return {}

    def getOptions(self):
        options = {'displayRowNumbers': 'true'}

        if self._viewStateDict != None:
            options.update(pu.mapViewStatePropsToJSChartProps(self._viewStateDict))

        return options

    def getTitle(self):
        return None

    def getDescription(self):
        return None

    def debugOut(self):
        debugMsg = str(self) + ": "
        debugMsg += "searchParams: " + str(self.getSearchParams())
        return debugMsg

_VIEW_ENTITY_CLASS = 'data/ui/views'

def getDashboardTitleAndPanels(dashboardName, namespace, owner, sessionKey):
    """ return a tuple of (dashboard-label, panel-list) from the dashboard entity specified by
        namespace/owner/dashboardName """
    # get the dashboard entity
    entityId = sm_dashboard.Dashboard.build_id(name=dashboardName, namespace=namespace, owner=owner)
    dashboard = sm_dashboard.Dashboard.get(id=entityId, sessionKey=sessionKey)

    label = dashboard.label
    baseSearch = {}
    baseSearch[pu.SP_SEARCH_TEMPLATE] = dashboard._obj.searchTemplate
    baseSearch[pu.SP_EARLIEST_TIME] = dashboard._obj.searchEarliestTime
    baseSearch[pu.SP_LATEST_TIME] = dashboard._obj.searchLatestTime

    # add the panels
    sequenceIndex = 0

    panelList = []
    dictionaryList = []

    # get_panel calls legacy.dashboard.getPanelBySequence which
    #  will throw an exception if no panel exists at the sequence index
    #  keep looping until that happens
    while True:
        try:
            panelDict = dashboard.get_panel(sequenceIndex)

            if panelDict != None:
                dictionaryList.append((panelDict, sequenceIndex))
            else:
                break
            sequenceIndex += 1
        except IndexError as e:
            # no more panels, break out of the while loop
            break

    for (dictionary, sequenceNum) in dictionaryList:
        try:
            panel = DashboardPanel(dictionary, sequenceNum, namespace, owner, sessionKey)
            panelList.append(panel)
        except Exception as e:
            logger.error("namespace=%s owner=%s dashboard=%s panelSequenceNum=%s error=%s" % 
                (namespace, owner, dashboardName, sequenceNum, str(e)))    

    return (label, panelList, baseSearch)

def getDashboardTitleAndPanelsFromXml(dashboardXml, namespace, owner, sessionKey):
    """ return a tuple of (dashboard-label, panel-list) 
        based on input of the entire dashboard XML string """

    # temporary fix until SPL-67161 is addressed
    logger.debug("dashboardXml=%s" % dashboardXml)
    dashboardXmlCorrectedBr = dashboardXml.replace("<br>", "<br/>")
    root = et.fromstring(dashboardXmlCorrectedBr)

    label = "untitled"    
    panelList = []
    sequenceIndex = 0
    for elem in root:
        if elem.tag == "label" and elem.text != None:
            label = elem.text.strip(" \n\t\r")
        elif elem.tag == "row":
            logger.info("row=%s" % et.tostring(elem, pretty_print=True))
            for panelElem in elem:
                panelDict = _getPanelDictFromXmlElem(panelElem)
                panel = DashboardPanel(panelDict, sequenceIndex, namespace, owner, sessionKey)
                sequenceIndex += 1
                panelList.append(panel)
        
    return (label, panelList)

def _getPanelDictFromXmlElem(panelElem):
    """ convert an XML representation of a panel into a dict representation
        the dict representation should be identical to what is retrieved from 
        legacy models models/dashboard_panel """

    panelDict = {}
    optionsDict = {}
    panelDict["type"] = panelElem.tag
    panelDict["title"] = ""
    
    if panelElem.tag == "html":
        html_content = None
        if normalizeBoolean(panelElem.attrib.get('encoded', False)):
            from lxml.html import fromstring, tostring

            html_content = tostring(fromstring(panelElem.text), method='xml')
        else:
            html_content = et.tostring(panelElem)
        optionsDict[pu.PP_RAW_CONTENT] = html_content
        titleElem = panelElem.find("title")
        if titleElem:
            panelDict["title"] = titleElem.text
    else:
        panelDict["searchLatestTime"] = "" 
        panelDict["searchEarliestTime"] = "" 

        for elem in panelElem:
            if elem.text:
                strippedText = elem.text.strip(" \n\t\r")
            else:
                strippedText = ""
            if elem.tag == "option":
                optionsDict[elem.get('name')] = strippedText
            elif elem.tag == "searchString":
                panelDict["searchCommand"] = strippedText
                panelDict["searchMode"] = "string"
            elif elem.tag == "searchName":
                panelDict["searchCommand"] = strippedText
                panelDict["searchMode"] = "saved" 
            elif elem.tag == "earliestTime":
                panelDict["searchEarliestTime"] = strippedText
            elif elem.tag == "latestTime":
                panelDict["searchLatestTime"] = strippedText
            elif elem.tag == "fields":
                if len(strippedText) and strippedText[0] == '[' and strippedText[-1] == ']':
                    fieldList = json.loads(strippedText)
                else:
                    fieldList = splunk.util.stringToFieldList(strippedText)
                panelDict["searchFieldList"] = [field.strip(" \n\t\r") for field in fieldList]
            else:
                panelDict[elem.tag] = strippedText
   
    if len(optionsDict) > 0:
        panelDict['options'] = optionsDict
   
    logger.debug("dashboard-xml panel xml=%s dict=%s" % (et.tostring(panelElem, pretty_print=True), panelDict))
 
    return panelDict


class DashboardPanel(AbstractViewType):
    _panelDict = {}
    _sequenceNum = 0

    def __init__(self, panelDict, sequenceNum, namespace, owner, sessionKey):
        self._namespace = namespace
        self._owner = owner
        self._sessionKey = sessionKey

        self._panelDict = copy.deepcopy(panelDict)
        self._sequenceNum = sequenceNum
        logger.debug("DashboardPanel::__init__> sequenceNum: " + str(self._sequenceNum) + ", panelDict: " + str(self._panelDict))

        searchParams = {}
        for searchParam in pu.SEARCH_PARAM_LIST:
            if searchParam in self._panelDict:
                searchParams[searchParam] = self._panelDict[searchParam]
        self.setSearchParams(searchParams)

        if searchParams.get(pu.SP_MODE, '') == 'saved':
            # retrieve the viewstate for the saved search
            savedSearchModel = pu.getSavedSearch(searchParams[pu.SP_COMMAND], namespace=namespace, owner=owner, sessionKey=sessionKey)
            self._viewStateDict = pu.getViewStatePropsFromSavedSearchModel(savedSearchModel, namespace=namespace, owner=owner, sessionKey=sessionKey)
            logger.debug("saved search model: %s" % str(savedSearchModel))
            self.isRealtime = savedSearchModel.is_realtime()
        else:
            self.isRealtime = pu.doInlineSearchParamsSpecifyRealtime(searchParams)

    def getViewIndex(self):
        return self._sequenceNum

    def getRenderTypes(self):
        return [self._panelDict['type']]

    def getChartProps(self):
        props = super(DashboardPanel, self).getChartProps()
        if 'options' in self._panelDict:
            props.update(pu.mapDashboardPanelOptionsToJSChartProps(self._panelDict['options']))
        
        return props

    def getMapProps(self):
        props = super(DashboardPanel, self).getMapProps()
        if 'options' in self._panelDict:
            mappingProps = {key.replace("mapping.",""):value for key, value in self._panelDict['options'].iteritems() if key.startswith("mapping")}
            props.update(mappingProps)

        logger.debug("map props: %s, options: %s" % (props, self._panelDict))
        return props

    def getTitle(self):
        return self._panelDict['title']

    def getDescription(self):
        return None

    def getOptions(self):
        options = super(DashboardPanel, self).getOptions()
        
        if 'options' in self._panelDict:
            if 'rowNumbers' in self._panelDict['options']:
                options['displayRowNumbers'] = self._panelDict['options']['rowNumbers']
            options.update(self._panelDict['options'])
        
        return options        

class Report(AbstractViewType):
    _savedSearchName = None
    _savedSearchModel = None
    _useViewState = False
    _isTransformingSearch_memo = None

    def __init__(self, savedSearchName, namespace=None, owner=None, sessionKey=None):
        self._namespace = namespace
        self._owner = owner
        self._sessionKey = sessionKey
        self._savedSearchName = savedSearchName
        self._savedSearchModel = pu.getSavedSearch(self._savedSearchName, namespace=namespace, owner=owner, sessionKey=sessionKey)
        self._viewStateDict = pu.getViewStatePropsFromSavedSearchModel(self._savedSearchModel, namespace=namespace, owner=owner, sessionKey=sessionKey)
        self.isRealtime = self._savedSearchModel.is_realtime()
        self._searchParams[pu.SP_MODE] = 'saved'
        self._searchParams[pu.SP_COMMAND] = self._savedSearchName
        logger.debug("Report::init> _savedSearchModel.ui.display_view: " + str(self._savedSearchModel.ui.display_view))
        logger.debug("Report::init> _viewStateDict: " + str(self._viewStateDict))

    def getRenderTypes(self):
        """ determine which render types to use for the report
        """ 
        if self._isTransformingSearch():
            showViz = normalizeBoolean(self._savedSearchModel.entity.get("display.visualizations.show", True))
            if showViz:
                reportVizType = self._savedSearchModel.entity.get("display.visualizations.type", "charting")
                renderVizType = None
                if reportVizType == "mapping":
                    renderVizType = 'map'
                elif reportVizType == "singlevalue":
                    renderVizType = 'single'
                else:
                    renderVizType = 'chart'
                return [renderVizType, 'table']
            else:
                return ['table']
        else:
            return ['event']

    def _isTransformingSearch(self):
        if self._isTransformingSearch_memo is not None:
            return self._isTransformingSearch_memo

        searchStr = self._savedSearchModel.search
        if not searchStr.strip().startswith(u'|'):
            searchStr = u'search ' + searchStr
        parsedSearch = Parser.parseSearch(str(searchStr), sessionKey=self._sessionKey, namespace=self._namespace, owner=self._owner)
        searchProps = parsedSearch.properties.properties

        self._isTransformingSearch_memo = "reportsSearch" in searchProps
        return self._isTransformingSearch_memo        

    def getChartProps(self):
        chartProps = {}

        if self._viewStateDict is None:
            chartProps = pu.getChartingPropsFromSavedSearchModel(self._savedSearchModel)
        else:
            chartProps = pu.mapViewStatePropsToJSChartProps(self._viewStateDict)
        
        logger.debug("chartProps = %s" % chartProps)

        return chartProps

    def getMapProps(self):
        mapProps = pu.getMapPropsFromSavedSearchModel(self._savedSearchModel)
        logger.debug("mapProps = %s" % mapProps)
        return mapProps
    
    def getOptions(self):
        options = {'displayRowNumbers': 'true'}

        if self._isTransformingSearch():
            options.update(self.getTableProps())
        else:
            options.update(self.getEventProps())

        return options
   
    def getEventProps(self):
        eventProps = {}

        if self._viewStateDict is None:
            eventProps = pu.getEventPropsFromSavedSearchModel(self._savedSearchModel)
        else:
            eventProps = pu.mapViewStatePropsToJSChartProps(self._viewStateDict)

        logger.debug("eventProps = %s" % eventProps)

        return eventProps
 
    def getTableProps(self):
        tableProps = {}

        if self._viewStateDict is None:
            tableProps = pu.getTablePropsFromSavedSearchModel(self._savedSearchModel)
        else:
            tableProps = pu.mapViewStatePropsToJSChartProps(self._viewStateDict)

        logger.debug("tableProps = %s" % tableProps)

        return tableProps

    def getTitle(self):
        title = None
        if self._viewStateDict != None and "ChartTitleFormatter" in self._viewStateDict:
            if "default" in self._viewStateDict["ChartTitleFormatter"]:
                title = self._viewStateDict["ChartTitleFormatter"]["default"]
        else:
            title = self._savedSearchName

        return title

    def getDescription(self):
        return pu.getDescriptionFromSavedSearchModel(self._savedSearchModel)

class SearchReport(AbstractViewType):
    _search = None
    _title = None

    def __init__(self, search, et='', lt='', title='Splunk search results',  namespace=None, owner=None, sessionKey=None):
        self._namespace = namespace
        self._owner = owner
        self._sessionKey = sessionKey
        self._searchParams[pu.SP_MODE] = 'inline'
        self._searchParams[pu.SP_COMMAND] = search
        self._searchParams[pu.SP_EARLIEST_TIME] = et
        self._searchParams[pu.SP_LATEST_TIME] = lt
        self._isRealtime = False
        self._title = title

    def getRenderTypes(self):
        searchStr = self._searchParams[pu.SP_COMMAND]
        if not searchStr.strip().startswith(u'|'):
            searchStr = u'search ' + searchStr
        parsedSearch = Parser.parseSearch(str(searchStr), sessionKey=self._sessionKey, namespace=self._namespace, owner=self._owner)
        searchProps = parsedSearch.properties.properties
        logger.debug("searchProps=%s" % searchProps)

        isTransformingSearch = "reportsSearch" in searchProps
        if isTransformingSearch:
            return ['chart', 'table']
        else:
            return ['event']

    def getTitle(self):
        return self._title
