import logging
import lxml.etree as et
import string
import urllib
import os
import os.path

import splunk
import splunk.rest as rest
import splunk.entity as entity
import splunk.appserver.mrsparkle.lib.viewstate as viewstate
import splunk.models.saved_search as sm_saved_search
import splunk.saved as saved

logger = logging.getLogger('splunk')
logger.propagate = 0

def getLogger():
    return logger

def logLogger(inspectLogger):
    """ recursively inspect the logger stack """
    logger.debug("logLogger inspectLogger=%s inspectLogger.name=%s inspectLogger.handlers=%s inspectLogger.propagate=%s" % (inspectLogger, inspectLogger.name, inspectLogger.handlers, inspectLogger.propagate))
    if inspectLogger.parent != None:
        logLogger(inspectLogger.parent)

SP_LATEST_TIME = 'searchLatestTime'
SP_COMMAND = 'searchCommand'
SP_MODE = 'searchMode'
SP_EARLIEST_TIME = 'searchEarliestTime'
SP_SID = 'searchSid'
SP_JOB_OBJ = 'searchJobObj'
SP_FIELD_LIST = 'searchFieldList'
SP_SEARCH_TEMPLATE = 'searchTemplate'

SEARCH_PARAM_LIST = [SP_LATEST_TIME, SP_COMMAND, SP_MODE, SP_EARLIEST_TIME, SP_FIELD_LIST]

PP_RAW_CONTENT = 'rawcontent'

SAVED_SEARCH_ENTITY_CLASS = 'saved/searches'	
# TODO: This should go into splunk.search	
def dispatchSavedSearch(searchName, namespace = None, owner = None, hostPath = None, sessionKey = None, forceHistoricSearch = False, overrideNowTime = None):
    """ start a saved search
        returns a tuple (sid, dispatchedJob)
        dispatchedJob is true unless the saved search job id returned is the historical artifact of a scheduled search """

    savedSearchModel = getSavedSearch(searchName, namespace=namespace, owner=owner, sessionKey=sessionKey)

    # check for scheduled saved search
    if savedSearchModel.schedule and savedSearchModel.schedule.is_scheduled:
        historicJob = saved.getJobForSavedSearch(searchName, namespace=namespace, owner=owner, hostPath=hostPath, sessionKey=sessionKey, useHistory=True)

        if historicJob != None:
            return (historicJob, False)

    args = {}
    if forceHistoricSearch:
        # don't dispatch a RT search. override dispatch arguments with non-RT timerange
        logger.debug("dispatchSavedSearch namespace=%s owner=%s" % (namespace, owner))
        if savedSearchModel.dispatch and savedSearchModel.dispatch.earliest_time:
            args['dispatch.earliest_time'] = savedSearchModel.dispatch.earliest_time.replace(u'rt', '')
        if savedSearchModel.dispatch and savedSearchModel.dispatch.latest_time:
            args['dispatch.latest_time'] = savedSearchModel.dispatch.latest_time.replace(u'rt', '')
        logger.debug("dispatchSavedSearch args=%s" % str(args))

    if overrideNowTime != None:
        args['dispatch.now'] = int(overrideNowTime)

    # assemble params
    uri = entity.buildEndpoint(SAVED_SEARCH_ENTITY_CLASS, searchName, namespace, owner)
    uri = uri + "/dispatch"
    logger.debug("dispatchSavedSearch> uri: " + uri);

    serverResponse, serverContent = rest.simpleRequest(uri, method="POST", sessionKey=sessionKey, rawResult=True, postargs=args)

    logger.debug("dispatchSavedSearch> serverResponse: " + str(serverResponse))
    logger.debug("dispatchSavedSearch> serverContent: " + str(serverContent))

    root = et.fromstring(serverContent)

    # catch quota overage; TODO: do something nicer
    if serverResponse.status == 503:
        extractedMessages = rest.extractMessages(root)
        for msg in extractedMessages:
            raise splunk.QuotaExceededException, msg['text']

    # normal messages from splunkd are propogated via SplunkdException;
    if 400 <= serverResponse.status < 600:
        extractedMessages = rest.extractMessages(root)
        for msg in extractedMessages:
            raise splunk.SearchException, msg['text']

    # get the search ID
    sid = root.findtext('sid').strip()

    # instantiate result object
    result = splunk.search.SearchJob(sid, hostPath, sessionKey, namespace, owner, dispatchArgs=args)

    return (result, True)

def prepareInlineSearchCommand(searchCommand):
    if searchCommand is None:
        raise Exception("No search command")
    logger.debug("prepareSearchCommand input search command: " + str(searchCommand))
    # if the first non-whitespace character is not a pipe or the word 'search', then prepend
    outputSearchCommand = searchCommand
    strippedSearchCommand = searchCommand.strip()
    if len(strippedSearchCommand) == 0 or strippedSearchCommand.startswith(u"|") == False:
        outputSearchCommand = 'search ' + searchCommand
    logger.debug("prepareSearchCommand output search command: " + str(outputSearchCommand))

    return outputSearchCommand

def doInlineSearchParamsSpecifyRealtime(searchParams):
    if SP_EARLIEST_TIME in searchParams and SP_LATEST_TIME in searchParams:
        return isTimerangeRealtime(searchParams[SP_EARLIEST_TIME], searchParams[SP_LATEST_TIME])
    return False
    
def isTimerangeRealtime(earliestTime, latestTime):
    isRealtime = False
    if earliestTime and earliestTime.strip().startswith(u'rt'):
        isRealtime = True
    elif latestTime and latestTime.strip().startswith(u'rt'):
        isRealtime =  True

    logger.debug("Earliest time, latest time: %s, %s specify realtime? %s" % (str(earliestTime), str(latestTime), str(isRealtime)))
    return isRealtime


def getViewState(vsid, namespace = None, owner = None, hostPath = None, sessionKey = None):
    """ gets a dictionary representation of the viewState specified by vsid """
    viewId = None
    if len(vsid.split(':')) is 1:
        viewId = '*'	# TODO: I don't understand this, found it in admin.py:1963
    output = viewstate.get(viewId, vsid, namespace=namespace, owner=owner, sessionKey=sessionKey)
    return output

def parseViewState(viewStateObj):
    """ parse a view state dictionary and returns a cleaned dictionary (i.e. without the _X_X_X suffix on keys) """
    viewStateDict = vars(viewStateObj)

    if 'modules' not in viewStateDict:
        raise KeyError('No "modules" key in viewStateDict')

    parsedData = {}

    debugMsg = ""
    for (k,v) in viewStateDict['modules'].iteritems():
        prefix, sep, seqInfo = str.partition(k, '_')
        parsedData[prefix] = v
        debugMsg += prefix + ": " + str(v) + "\n"

    logger.debug("parseViewState> parsedData: " + debugMsg)
    return parsedData

def getViewStateChartType(viewStateProps):
    return viewStateProps['ChartTypeFormatter']['default']

    # TODO: continue filling output prop mapping
_IGNORE = 'ignore'
_viewStateToJSChartMapping = { 
    'NullValueFormatter':         {'default': 'chart.nullValueMode'},
    'StackModeFormatter':         {'default': 'chart.stackMode'},
    'LegendFormatter':            {'default': 'legend.placement'},
    'SplitModeFormatter':         {'default': 'layout.splitSeries'},
    'XAxisTitleFormatter':        {'default': 'primaryAxisTitle.text'},
    'YAxisTitleFormatter':        {'default': 'secondaryAxisTitle.text'},
    'YAxisRangeMinimumFormatter': {'default': 'secondaryAxis.minimumNumber'},
    'YAxisRangeMaximumFormatter': {'default': 'secondaryAxis.maximumNumber'},
    'AxisScaleFormatter':         {'default': 'secondaryAxis.scale'},
    'JSChart':                    {'height':  _IGNORE},
    'ChartTypeFormatter':         {'default': 'chart'},
    'LineMarkerFormatter':        {'default': 'chart.showMarkers'},
    'DataOverlay':                {'default': _IGNORE, 'dataOverlayMode': _IGNORE}, #TODO: replace _IGNORE
    'ChartTitleFormatter':        {'default': 'chartTitle'},
    #TODO: find appropriate JSChart conversions for below
    'Segmentation':               {'default': 'segmentation.default', 'segmentation': 'segmentation.segmentation'},
    'FlashTimeline':              {'minimized': _IGNORE, 'height': _IGNORE},
    'FieldPicker':                {'sidebarDisplay': 'sidebarDisplay', 'fields': 'sidebarDisplay.fields'},
    'MaxLines':                   {'default': 'maxLines.default', 'maxLines': 'maxLines.maxLines'},
    'ButtonSwitcher':             {'selected': _IGNORE},
    'SoftWrap':                   {'enable': 'softWrap.enable'},
    'RowNumbers':                 {'default': 'displayRowNumbers', 'displayRowNumbers': 'displayRowNumbers'},
    'Count':                      {'default': _IGNORE},
    'is':                         {'autogen': _IGNORE},
    'SearchMode':                 {'searchModeLevel': _IGNORE},
    }

# deprecation map from ViewStateAdaptor.js
_viewStateDeprecationMap = {
        'Count':         {'count' : 'default'},
        'MaxLines':      {'maxLines' : 'default'},
        'RowNumbers':    {'displayRowNumbers' : 'default'},
        'Segmentation':  {'segmentation' : 'default'}
    }

def mapViewStatePropsToJSChartProps(viewStateProps):
    """ map the data in the viewstate properties into a format that can be passed to the JSCharting system """

    chartProps = {}
    logger.debug("mapViewStatePropsToJSChartProps> viewStateProps: " + str(repr(viewStateProps)))
    for k, v in viewStateProps.items():
        if k in _viewStateToJSChartMapping:
            for subK, subV in v.items():
                if subK in _viewStateToJSChartMapping[k]:
                    
                    # check for deprecation
                    if k in _viewStateDeprecationMap:
                        if subK in _viewStateDeprecationMap[k]:
                            if _viewStateDeprecationMap[k][subK] in v:
                                # newer value is present, ignore this
                                logger.debug("mapViewStatePropsToJSChartProps> deprecated view state prop '%s[%s]=%s' when new prop '%s[%s]=%s' is present" % (k, subK, subV, k, _viewStateDeprecationMap[k][subK], v[_viewStateDeprecationMap[k][subK]]))
                                continue

                    if _viewStateToJSChartMapping[k][subK] is not _IGNORE:
                        chartProps[_viewStateToJSChartMapping[k][subK]] = subV
                    else:
                        logger.debug("mapViewStatePropsToJSChartProps> ignoring view state prop: " + k + ", " + subK)
                else:
                    logger.warn('Unknown subkey in viewStateProps[' + str(k) + '] = ' + subK)
        else:
            logger.warn('Unknown key in viewStateProps: ' + str(k))

    return chartProps

def getSavedSearch(savedSearchName, namespace = None, owner = None, sessionKey = None):
    entityId = sm_saved_search.SavedSearch.build_id(name=savedSearchName, namespace=namespace, owner=owner)
    logger.debug("getViewStatePropsFromSavedSearch> entityId: " + str(entityId))
    savedSearchModel = sm_saved_search.SavedSearch.get(id=entityId, sessionKey=sessionKey)
    return savedSearchModel

def getViewStatePropsFromSavedSearchName(savedSearchName, namespace = None, owner = None, sessionKey = None):
    savedSearchModel = getSavedSearch(savedSearchName, namespace=namespace, owner=owner, sessionKey=sessionKey)
    return getViewStatePropsFromSavedSearchModel(savedSearchModel, namespace=namespace, owner=owner, sessionKey=sessionKey)

def getViewStatePropsFromSavedSearchModel(savedSearchModel, namespace = None, owner = None, sessionKey = None):
    if savedSearchModel != None and savedSearchModel.ui != None and savedSearchModel.ui.vsid != None:
        try:
            logger.debug("attempting to retrieve and parse viewstate. savedSearchModel.id=%s savedSearchModel.ui=%s savedSearchModel.ui.vsid=%s " % (str(savedSearchModel.id), str(savedSearchModel.ui), str(savedSearchModel.ui.vsid)))
            # retrieve the viewState and clean up the output
            viewState = getViewState(savedSearchModel.ui.vsid, namespace=namespace, owner=owner, sessionKey=sessionKey)
            return parseViewState(viewState)
        except Exception as e:
            logger.warning("Exception raised while retrieving or parsing viewstate. Will ignore viewstate while formatting for PDF. saved_search.id=%s exception=%s" % (savedSearchModel.id, str(e)))
            return None
    else:
        return None

# the following getXXXPropsFromSavedSearchModel functions extract properties from
# a saved search entity that has display properties (from Bubbles on)
def getChartingPropsFromSavedSearchModel(savedSearchModel):
    return extractSpecificProps(savedSearchModel, "display.visualizations.charting", "display.visualizations.charting.")

def getEventPropsFromSavedSearchModel(savedSearchModel):
    return extractSpecificProps(savedSearchModel, "display.events", "display.events.")

def getTablePropsFromSavedSearchModel(savedSearchModel):
    return extractSpecificProps(savedSearchModel, "display.statistics", "display.statistics.")

def getMapPropsFromSavedSearchModel(savedSearchModel):
    return extractSpecificProps(savedSearchModel, "display.visualizations.mapping", "display.visualizations.mapping.")

_savedSearchModelPropsKeyChange = {
    "rowNumbers": "displayRowNumbers"
    }

def extractSpecificProps(savedSearchModel, selectorPrefix, removePrefix):
    """ pull out all props in the savedSearchModel that start with selectorPrefix,
        remove "removePrefix" from each of the props
        rename the props' keys according to the _savedSearchModelPropsKeyChange map
    """

    # get the dict-like entity object
    props = savedSearchModel.entity

    # get all items in props with a key prefixed by selectorPrefix, and then remove from the key removePrefix
    extractedProps = {key.replace(removePrefix, ""):props[key] for key in props if key.startswith(selectorPrefix)} 

    # rename any props as necessary
    renamedProps = {_savedSearchModelPropsKeyChange.get(key, key):extractedProps[key] for key in extractedProps}

    return renamedProps

def getDescriptionFromSavedSearchModel(savedSearchModel):
    return savedSearchModel.entity.get("description")

_chartingPropsToIgnore = [ 
    'drilldown',
    'count',
    'displayRowNumbers'
    ]

def mapDashboardPanelOptionsToJSChartProps(panelProps):
    """ maps from the keys in the panelDict['options'] dictionary to JS Charting props """
    chartProps = {}

    for key in panelProps:
        if key.startswith('charting.'):
            chartingKey = key[len('charting.'):]
            if not chartingKey in _chartingPropsToIgnore:
                chartProps[chartingKey] = panelProps[key]

    logger.debug("mapDashboardPanelPropsToJSChartProps> panelProps: " + str(repr(panelProps)) + ", chartProps: " + str(repr(chartProps)))

    return chartProps

