import cherrypy
from splunk.appserver.mrsparkle import *
from splunk.appserver.mrsparkle.lib import i18n
import splunk.searchhelp.searchhelper as sh
import splunk.search as se
import splunk.util
import logging

import re
import xml.sax.saxutils as su
import splunk.bundle as bundle
import splunk.mining.FieldLearning as ifl
import splunk.mining.MultiFieldLearn as mfl


logger = logging.getLogger('splunk.appserver.controllers.ifx')

RULES_BY_EVENTTYPES = False

_STRING_DELIMITER = "\n"
MAX_SAMPLES = 100
MIN_SAMPLES = 20
MAX_LINES = 15
MAX_FIELDS = 7  # PREVENT ABUSE

requiredFields = [] #["sid", "offset", "fieldname", "examples", "counterexamples"]

CERROR = "error"
CWARN  = "warn"
CMSG   = "info"

CVALIDLIST = [CERROR, CWARN, CMSG]

def errorCMP(x,y):
    x = re.search('class="(.*?)"', x).group(1)    
    y = re.search('class="(.*?)"', y).group(1)    
    return cmp(CVALIDLIST.index(y),CVALIDLIST.index(x))

def addMessage(parent, msg, msgtype):
    if msgtype not in CVALIDLIST:
        raise Exception("Invalid message type '%s' for '%s'" % (msgtype, msg))
    if type(parent) == dict:
        parent = parent['messages']
    msgtxt = '<p class="%s">%s</p>' % (su.escape(msgtype), su.escape(msg))
    if msgtxt not in parent:
        parent.append(msgtxt)


def llog(msg):
    pass
    #f = open("/tmp/debug.txt", "a")
    #f.write(msg + "\n")
    #f.close()


# split on comma by default.
# if value has comma and user wants to use a different separator,
# use pattern: #val1#val2#val3#, where # can be any non-alnum char
# e.g. "/foo/bar/baz/", "@10,11@12,13@"
def splitExampleValues(text):
    tlen = len(text)
    if tlen == 0:
        return []
    if tlen == 1:
        return [text]
    firstch = text[0]
    if not firstch.isalnum() and firstch == text[-1] and text.count(firstch) > 2:
        return text[1:-1].split(firstch)
    return text.split(",")

    
class IFXController(BaseController):
    """/ifx"""

    @route('/')
    @expose_page(must_login=True, methods=['GET', 'POST'])
    def index(self, **kwargs):

        args = getArgs(kwargs)

        try:
            regex = args['regex']
            if len(regex)>0 and saveRule(regex, args):
                templateArgs = generateOutput(args, [], None, regex, None)
                return self.render_template('ifx/index.html', templateArgs)
        # work around bugs in bundle.py's getConf()
        except AttributeError, e:
            addMessage(args, _("Unable to save rule: %s") % e, CERROR)
            # import traceback
            # addMessage(args, "<pre>Stacktrace: %s</pre>" % traceback.format_exc(), CWARN)

        events = []
        fullevents = []
        try:
            events, fullevents = getSampleEvents(args['sessionkey'], args['samplesearch'], args['maxtime'], args['messages'])
            llog("EVENTS: %s" % events)
        except Exception, e:
            addMessage(args, _("Unable to get sample events: %s") % e, CERROR)

        examples = list(args['examples']) # make copy to prevent modification
        regex = ""

        # if user hit 'preview' ignore that he previously edited the regex
        if 'preview' in kwargs:
            args['edited'] = False

        # if user modified regex and didn't hit preview button, use his; otherwise learn it
        if args['edited']:
            regex = args['regex']
            # args['examples'] = []
            args['counterexamples'] = []
        else:
            try:
                # run through user examples, to see if the user specified multiple values per example
                seenMultipleValues = False
                for exampleSet in examples:
                    vals = splitExampleValues(exampleSet)
                    if len(vals) > 1:
                        seenMultipleValues = True
                        break
                # if no multiple values, use standard ifx learning
                if not seenMultipleValues:
                    regexes, extractions = ifl.learn(events, examples, args['counterexamples'])
                    if len(regexes) > 0:
                        regex = regexes[0]
                else: # if multiple values, use in multivalue ifx
                    counterExamples = args['counterexamples']
                    # !! hack
                    counterExamples = { 'field0': counterExamples } 
                    sourceField = "_raw"
                    markedEvents = {}
                    for i, event in enumerate(events):
                        markedEvent = {}
                        raw = event
                        markedEvent["_event"] = { sourceField : raw } 
                        for exampleSet in examples:
                            #  !! hack
                            pos = 0
                            vals = splitExampleValues(exampleSet)
                            # PREVENT ABUSE
                            if len(vals) > MAX_FIELDS:
                                addMessage(args, _("Too many fields specified for extraction.  Using first %s values.") % MAX_FIELDS, CWARN)
                                vals = vals[:MAX_FIELDS] 
                            for example in vals:
                                pos += 1
                                llog("EXAMPLE: %s" % example)
                                if example in raw:
                                    llog("FOUND: example %s raw %s" % (example, raw))
                                    markedEvent["FIELDNAME%s" % pos] = example
                        markedEvents[i] = markedEvent
                    for i, me in markedEvents.items():
                        llog("ME: %s" % me)
                    rules = mfl.learn("_raw", markedEvents, counterExamples)

                    regexes = [rule.getPattern() for rule in rules]
                    llog("EXAMPLES: %s %s" % (examples, type(examples)))
                    llog("REGEXES: %s" % regexes)
                    # for id, e in markedEvents.items():
                    #    for rule in rules:
                    #        extractions = rule.findExtractions(e)
                    # regexes, extractions = mfl.learn(events, examples, args['counterexamples'])
                    if len(regexes) > 0:
                        regex = regexes[0]
                    
            except Exception, e:
                llog("PROBLEM: %s" % e)
                import traceback
                llog(traceback.format_exc())
                
                logger.warn("Problem learning pattern: %s" % e)

        # if we have some exammple values, but couldn't get any regex, give warning
        if len(examples) > 0 and len(regex) == 0:
            addMessage(args, _("No regex could be learned.  Try providing different examples or restriction."), CWARN)

        testingurl = None
        try:
            # warn about conflicts
            if not fieldNameExtractionExists(args, regex):
                testingurl =  self.getTestURL(regex, args)
        except Exception, e:
            addMessage(args, _("Unable to determine if fieldname exists: %s" % e), CWARN)
            llog("PROBLEM: %s" % e)
            import traceback
            llog(traceback.format_exc())
            logger.warn("Problem determining if fieldname exists: %s" % e)


        logger.debug('OUTPUT RULE: %s' % regex)
        cherrypy.response.headers['content-type'] = MIME_HTML
        templateArgs = generateOutput(args, events, fullevents, regex, testingurl)
        return self.render_template('ifx/index.html', templateArgs)

    def getTestURL(self, regex, args):
        if len(regex) > 0:
            xfields = re.findall("\?P<(.*?)>", regex)
            if len(xfields) > 0:
                xfieldslist = ', '.join(xfields)
                # if you want to match '\' the regex would have to be '"\\" - an extra escaping layer is needed by search language
                regex = regex.replace('\\', '\\\\')
                regex = regex.replace('"', '\\"')
                return self.make_url(['app', args.get('namespace'), 'flashtimeline'],  _qs=[('q', 'search %s | head 10000 | rex "%s" | top 50 %s' % (args['samplesearch'], regex, xfieldslist))])
            addMessage(args, _('Regex does not extract any named fields.'), CWARN)

        return None

def getSampleEvents(sessionKey, sampleSearch, maxtime, messages):
    logger.debug( "SAMPLESEARCH: %s" % sampleSearch)
    if sampleSearch == '':
        return [],[]

    query = "search %s | head %s | abstract maxlines=%s " % (sampleSearch, MAX_SAMPLES, MAX_LINES)
    logger.debug("QUERY: %s" % query)
    logger.debug("MAXTIME: %s" % maxtime)
    results = []
    if maxtime != None:
        # try to use maxtime to get selecteed event at top
        epochmaxtime = splunk.util.dt2epoch(splunk.util.parseISO(maxtime))
        results = se.searchAll(query, sessionKey=sessionKey, latest_time=epochmaxtime, status_buckets=1)
        logger.debug( "RESULTS1: %s" % len(results))
    #addMessage(messages, "ONLY %s events with maxtime = %s '%s'" % (len(results), maxtime, query), CWARN)
    #print "ONLY %s events with maxtime = %s '%s'" % (len(results), maxtime, query)

    # if not enough events, research without time constraint
    if len(results) < MIN_SAMPLES:
        results = se.searchAll(query, sessionKey=sessionKey, status_buckets=1)
        logger.debug( "RESULTS2: %s" % len(results))
        
    return ([ r.raw.getRaw() for r in results ], results)

def cleanVal(val):
    whitespaceCleaner = re.compile(r'\s*(\r?\n)+\s*')
    return whitespaceCleaner.sub('\n', val.strip())

def getCleanListVal(val):
    if val == None or val == "":
        return []
    return cleanVal(val).split(_STRING_DELIMITER)

def addOneSecond(isotime):
    if isotime == "":
        return None
    import splunk.util,datetime
    timestamp = splunk.util.parseISO(isotime)
    timestamp += datetime.timedelta(seconds=1)
    return splunk.util.getISOTime(timestamp)

def quoteVal(val):
    val = val.replace('\\', '\\\\')
    return '"%s"'% val.replace('"', '\\"')

def dequoteVal(val):
    if len(val) > 1 and val.startswith('"') and val.endswith('"'):
        val = val.replace('\\\\', '\\')
        val = val[1:-1].replace('\\"', '"')
    return val

def getFieldValue(event, field, defaultVal, messages):
    val = defaultVal
    try:
        if field == "_raw":
            val = event.raw.getRaw()
        elif field in event:
            fieldValues = event[field]
            if len(fieldValues) > 0:
                val = fieldValues[0].value
        #print field,val
    except:
        addMessage(messages, _("Unable to get value of '%s' field on event.  Using the default value '%s'.") % (field, val), CWARN)
        
    return cleanVal(val)

def getArgs(requestArgs):
    messages = []

    for field in requiredFields:
        if field not in requestArgs:
            raise AttributeError, 'Required field "%s" not provided' % field

    username   = cherrypy.session['user']['name']
    sessionKey = cherrypy.session['sessionKey']
    namespace  = requestArgs.get('namespace','search')
    sid        = requestArgs.get('sid','')
    soffset    = requestArgs.get('offset','')
    search     = requestArgs.get('search','')
    oldsearch  = requestArgs.get('oldsearch','')
    regex      = requestArgs.get('regex','').strip()

    fieldname = cleanVal(requestArgs.get('fieldname',''))
    examples = getCleanListVal(requestArgs.get('examples',''))
    counterexamples = getCleanListVal(requestArgs.get('counterexamples',''))

    for example in examples:
        if example in counterexamples:
            addMessage(messages, _("Ignoring '%s' as a counter example, as it is already an example value to extract.") % example, CWARN)
            counterexamples.remove(example)

    event = getEvent(sid, soffset, search, messages)

    if len(examples) == 0:
        addMessage(messages, _('Please specify example field values.'), CMSG)

    # if there are messages shown, run the learner but don't save; assume
    # that all messages that occur before this point invalidate a save
    saveresults = 'save' in requestArgs
    editedrule = requestArgs.get('edited','') == "True"

    raw =  ""
    index = "main"
    sourcetype = host = source = ""
    eventtypes = None
    maxtime = None
    if event != None:
        sourcetype = getFieldValue(event, 'sourcetype', "", messages)
        source     = getFieldValue(event, 'source', "", messages)
        host       = getFieldValue(event, 'host', "", messages)
        index      = getFieldValue(event, 'index', "main", messages)
        raw        = getFieldValue(event, '_raw', "", messages)
        maxtime    = addOneSecond(getFieldValue(event, '_time', "", messages))

        if RULES_BY_EVENTTYPES:
            if 'eventtype' in event:
                eventtypes = [et.value for et in event['eventtype']]

    restriction = ''
    # if user didn't change the search and we have a restriction, trust it
    if search == oldsearch and 'restrictto' in requestArgs:
        restriction = requestArgs['restrictto']
    else:
        if eventtypes != None:
            # first eventtype            
            restriction = 'eventtype=%s' % quoteVal(eventtypes[0].replace('"', '\\"'))
        elif sourcetype != "":
            restriction = 'sourcetype=%s' % quoteVal(sourcetype)
        elif source != "":
            restriction = 'source=%s' % quoteVal(source)
        elif host != "":
            restriction = 'host=%s' % quoteVal(host)
        else:
            pass  #raise "No filterable attributes (eventtype, sourcetype, source, host) found on event."

    oldsearch = search

    # assemble values for 'restrict to' drop down
    restrictionValues = []
    if sourcetype != '': restrictionValues.append('sourcetype=%s' % quoteVal(sourcetype))
    if source     != '': restrictionValues.append('source=%s'     % quoteVal(source))
    if host       != '': restrictionValues.append('host=%s'       % quoteVal(host))

    if eventtypes != None:
        for et in eventtypes:
            restrictionValues.append('eventtype=' + et.quoteVal())
    restrictionValues.sort()

    if restriction == '':
        samplesearch = ''
    else:
        samplesearch =  "index=%s %s" % (index, restriction)

    return {'username':username, 'sessionkey':sessionKey,
            'namespace': namespace,
            'messages' :messages,  'fieldname':fieldname,
            'regex': regex,
            'examples':examples, 'counterexamples':counterexamples,
            'saveresults':saveresults, 'edited':editedrule,
            'eventraw':raw, 'restriction':restriction,
            'restrictionvalues':restrictionValues,
            'samplesearch':samplesearch,
            'sid': sid,
            'soffset':soffset,
            'maxtime':maxtime,
            'search':search,
            'oldsearch':oldsearch,
            'successmessage': ''
        }

def getEvent(sid, soffset, search, messages):
    if sid == '' and soffset == '' and search == '':
        return None
    invalid = None
    try:
        if sid != '' and soffset != '':
            job = se.getJob(sid)
            return job.events[int(soffset)]
    except Exception, e:
        invalid = e

    if invalid != None:
        msg = _('Invalid search job/offset specified. %s. ') % invalid
    else:
        msg = _('No search job/offset specified.')
    addMessage(messages, msg + _(' Defaulting to using values from the first result of the search string: "%s"') % search, CWARN)

    try:
        return se.searchOne("search %s |head 1" % search, status_buckets=1)
    except:
        addMessage(messages, _('No search results from search string: "%s"') % search, CWARN)
        return None


def illegalFieldCharacters(name):
    return re.match("^[a-zA-Z0-9_]+$", name) == None

def invalidFieldName(fieldname, messages):
    warning = None
    if fieldname == "":
        warning = _('Please specify the field name.')
    elif fieldname[0].isdigit(): # can't start with num
        warning = _('Field name cannot start with a digit.')
    elif illegalFieldCharacters(fieldname):
        warning = _('Invalid characters in field name; only "a-z0-9_" are allowed.')
    elif len(fieldname) > 30:
        warning = _('Field name is too long.')
    if warning != None:
        warning += _(" Regex not saved.")
        addMessage(messages, warning, CERROR)
    return warning != None


def removeFieldExtractionName(regex):
    return re.sub("(\?P?<.*?>)", "", regex)

def prettyList(l, conj="and"):
    output = ""
    llen = len(l)
    if llen == 0:
        return ""
    if llen == 1:
        return l[0]
    if llen == 2:
        return "%s %s %s" % (l[0], conj, l[1])
    for i, v in enumerate(l):
        if output != "":
            output += ", "
        if i == llen-1:
            output += conj +  " " 
        output += str(v)
    return output

def attributesAlreadyExtracted(fullevents, allextractions, args):
    knownSet = set()
    for attr, extractions in allextractions.items():
        valuesAlreadyExtracted(fullevents, extractions, args)

def valuesAlreadyExtracted(fullevents, extractions, args):
        
    maxCount = float(len(extractions))
    if maxCount == 0:
        return
        
    values = {}
    for event in fullevents:
        for attr in event:
            val = getFieldValue(event, attr, None, args)
            if attr not in values:
                values[attr] = set()
            values[attr].add(val)

    #addMessage(args, "VALUES: %s" % values, CMSG)
    bestCount = 0
    bestAttr = None
    for attr, vals in values.items():
        common = len(extractions.intersection(vals))
        #addMessage(args, "ATTR %s VALS %s<br>" % (attr, vals), CMSG)        
        if common > bestCount:
            bestCount = common
            bestAttr = attr
    percent = bestCount / maxCount
    if percent > 0.0:
        level = CWARN        
        if percent < .2:
            qualifier = "some of"
        elif percent < 0.5:
            qualifier = "many of"
        elif percent < 1.:
            qualifier = "most of"
        else:
            qualifier = ""
            #level = CERROR
        addMessage(args, _("Note: %s the values you want may already be extracted in the '%s' field.  ") % (qualifier, bestAttr), level)
            
        
    

def fieldNameExtractionExists(args, regex, fieldname=None):

    sessionkey = args['sessionkey']
    namespace = args['namespace']
    owner     = args['username']
    restriction = args['restriction']
    messages = args['messages']

    if restriction.startswith("sourcetype="):
        restriction = restriction[len("sourcetype="):]

    fieldError      = []
    fieldWarn       = []
    extractionError = []
    extractionWarn  = []
    # print "sessionkey:", sessionkey
    # print "namespace:", namespace
    # print "owner:", owner
    props = bundle.getConf('props', sessionkey, namespace, owner)
    ifMyRegexHadNoNames = removeFieldExtractionName(regex)
    # for each prop stanza
    for stanzaname in props.keys():
        stanza = props[stanzaname]
        stanzaname = stanzaname.replace("::", '=')
        # for each attribute
        for attr,val in stanza.items():
            # we have an EXTRACTION
            if attr.startswith("EXTRACT"):
                # if we have a fieldname (we're saving) and we have an extraction already for the fieldname
                if fieldname != None and (("?P<%s>" % fieldname) in val or ("?<%s>" % fieldname) in val):
                    if stanzaname == restriction:
                        # crap the exact stanza we care about already has this fieldname!!
                        fieldError.append(stanzaname)
                    else:
                        # note the stanza
                        fieldWarn.append(stanzaname)
                else:
                    ifYouHadNoNames = removeFieldExtractionName(val)
                    if ifYouHadNoNames == ifMyRegexHadNoNames:
                        fieldnames = '/'.join(re.findall("\?P?<(.*?)>", val))
                        if stanzaname == restriction:
                            extractionError.append((stanzaname, fieldnames))
                        else:
                            extractionWarn.append((stanzaname, fieldnames))

    if len(fieldError) > 0:
        addMessage(messages, _("'%s' is already extracted for %s.") % (fieldname, prettyList(stanzaname)), CERROR) 
    if len(fieldWarn) > 0:
        addMessage(messages, _("Note: '%s' is currently also being extracted for %s") % (fieldname, prettyList(stanzaname)), CMSG)
    if len(extractionError) > 0:
        pairs = ["%s for %s" % (stanzaname, fieldnames) for fieldnames, stanzaname in extractionError]
        addMessage(messages, _("This regex already extracts %s.") % prettyList(pairs), CERROR)
    if len(extractionWarn) > 0:
        pairs = ["%s for %s" % (stanzaname, fieldnames) for fieldnames, stanzaname in extractionWarn]
        addMessage(messages, _("Note: This regex already extracts %s.") % prettyList(pairs), CWARN)

    return len(fieldError) > 0 or len(extractionError) > 0


def saveRule(regex, args):
    sessionkey = args['sessionkey']
    namespace = args['namespace']
    owner     = args['username']
    fieldname = args['fieldname']
    restriction = args['restriction']
    messages = args['messages']
    shouldSave = args['saveresults'] == True

    if not shouldSave or len(regex) == 0:
        return False

    # add support for multiple field names
    fieldnames = fieldname.split(",")
    # only one field
    if len(fieldnames) == 1:
        regex = regex.replace("?P<FIELDNAME>", "?P<%s>" % fieldname)
    else:
        # split name into multple names (e.g. "status,code,url" then rename FIELDNAME1->status, FIELDNAME2->code, ...
        for i, fname in enumerate(fieldnames):
            fname = fname.strip()
            if invalidFieldName(fname, messages):            
                return False            
            regex = regex.replace("?P<FIELDNAME%s>" % (i+1), "?P<%s>" % fname)
    # still some unnamed fields!
    unnamedCount = regex.count("?P<FIELDNAME")
    if unnamedCount > 0:
        addMessage(messages, _("Each field must have a name.  %s field(s) do not have names." % unnamedCount), CERROR)
        return False

    # verify user rule has extractions
    if args['edited']:
        fields = re.findall("\?P<(.*?)>", regex)
        if len(fields) == 0:
            addMessage(messages, _("Regex '%s' does not contain a named extraction (e.g. '(?P<fieldname>\w+)')"), CERROR)
            return False
        # set fieldname to pretty name of all extractions it gets
        attrSuffix = '-'.join(fields)
    else:
        attrSuffix = fieldname

    # props.conf weirdness -- [sourcetype::name] doesn't
    # match.  need to use [name].  only for 'sourcetype'.
    # other attributes: source, host, and eventtype work
    # with their type::name.
    # stanza = restriction.replace('=', '::')
    stanza = re.sub("^(source|sourcetype|host|eventtype)(=)", "\\1::", restriction)
    if stanza.startswith("sourcetype::"):
        stanza = stanza[len("sourcetype::"):]
    # dequote stanzas. e.g. 'host="localhost"' --> 'host=localhost'
    colon = stanza.find('::')
    if colon > 0:
        stanza = stanza[:colon] + "::" + dequoteVal(stanza[colon+2:])
    else:
        stanza = dequoteVal(stanza)


    if regex.endswith("\\\\"):
        regex = regex[:-2] + "[\\\\]"
    if fieldNameExtractionExists(args, regex, fieldname):
        return False
    
    props = bundle.getConf('props', sessionkey, namespace, owner)
    props.createStanza(stanza)

    # write out each regex to props.conf
    logger.debug("STANZA: [%s] '%s' = '%s'" % (stanza, "EXTRACT-" + attrSuffix, regex))
    props[stanza]["EXTRACT-" + attrSuffix] = regex

    successmsg = _("'%s' is now extracted as a field.") % fieldname
    addMessage(messages, successmsg, CMSG)
    args['successmessage'] = successmsg 
    return True

# Returns a list of dict objects that don't have overlapping 'start' and 'end' indexes.  Assume that start > end.  If an overlapping list item
# exists, the later item is deleted. for start/end pair (i,j), any subsequent pair (m,n) will be removed if i <= m <= j or i <= n <= j.
def removeOverlappingBoundaries(boundaryList):
    if len(boundaryList) < 2: return boundaryList
    killList = []
    #print "BOUNDARYLIST:", boundaryList

    for pivot, base in enumerate(boundaryList):
        for idx, challenge in enumerate(boundaryList[pivot+1:]):
            if (base['start'] <= challenge['start'] <= base['end']) or \
               (base['start'] <= challenge['end'] <= base['end']):
               killList.append(pivot + 1 + idx)
    return [x for (idx, x) in enumerate(boundaryList) if idx not in killList]

LT = "*xXx*"
GT = "*yYy*"

# Renders the interactive field learner interface
def generateOutput(args, events, fullevents, regex, testingurl):

    username        = args['username']
    namespace       = args['namespace']
    sessionKey      = args['sessionkey']
    messages        = args['messages']
    fieldname       = args['fieldname']
    examples        = args['examples']
    counterexamples = args['counterexamples']
    saveresults     = args['saveresults']
    eventraw        = args['eventraw']
    restriction     = args['restriction']
    restrictionvalues = args['restrictionvalues']
    samplesearch    = args['samplesearch']
    sid             = args['sid']
    soffset         = args['soffset']
    search          = args['search']
    oldsearch       = args['oldsearch']
    edited          = args['edited']
    successmessage  = args['successmessage']

    # if the field learner is just opened, display message and don't get any events

    allextractions = {}

    # attach regex color highlighting
    # The basic heuristic here is to attempt to color every regex match
    # within each event.
    # 1.  each regex will be applied only once per string
    # 2.  on overlapping matches, only the first will be used
    #
    # generate the list of matching events, and marking the extracted fields
    # we first have to mark the change boundaries, otherwise overlapping regexes will
    # obliterate each other's matches

    # odd replacement needed to keep <>'s but escape values between, while still maintaining positional information for regex matches
    if edited:
        format = '<span class=highlight "m m%s">%s</span>'
    else:
        format = '<span class=highlight "m m%s"><a href="#" class="term" term="%s" title="Remove this term">%s</a></span>'

    format = format.replace('<', LT)
    format = format.replace('>', GT)


    examplesNotSeen = set()
    for example in examples:
        for val in splitExampleValues(example):
            examplesNotSeen.add(val)


    outputevents = []
    r = None
    try:
        r = re.compile(regex)
        i = 0
        attrclass = {}
        # for each event
        for j, eventtext in enumerate(events):
            changeBoundaries = []
            # SPL-32558. only match the first time
            ### for each match
            ### for m in r.finditer(eventtext):
            m = r.search(eventtext)
            if m != None:
                attrvals = m.groupdict()
                # for each named group
                for attr in attrvals.keys():
                    val = m.group(attr)
                    # don't allow newline in value because they get replaced with <br> right in the text and confuse
                    # the list code that separates values by newliens! val = val.replace('\n',' ').strip()
                    if val in examplesNotSeen:
                        examplesNotSeen.remove(val)
                    # add mapping of attr to set of values
                    if attr in allextractions:
                        allextractions[attr].add(val)
                    else:
                        allextractions[attr] = set([val])
                        attrclass[attr] = i
                        i += 1
                    changeBoundaries.append({ 'start': m.start(attr), 'end': m.end(attr), 'replacement': val, 'class': attrclass[attr]})                        

            offset = 0
            changeBoundaries.sort(lambda x,y: cmp(x['start'],y['start']))

            for boundary in removeOverlappingBoundaries(changeBoundaries):
                val = boundary['replacement']
                if edited:
                    newValue = format % (boundary['class'], val)
                else:
                    newValue = format % (boundary['class'], val, val)
                eventtext = eventtext[:boundary['start'] + offset] + newValue + eventtext[boundary['end'] + offset:]
                offset += len(newValue) - (boundary['end'] - boundary['start'])

            eventtext = su.escape(eventtext)
            eventtext = eventtext.replace('\n', '<br/>')
            eventtext = eventtext.replace(LT, '<')
            eventtext = eventtext.replace(GT, '>')
            outputevents.append(eventtext)

    except Exception, e:
        #import traceback
        #addMessage(args, "<pre>Stacktrace: %s</pre>" % traceback.format_exc(), CWARN)
        #addMessage(messages, 'regex: %s' % regex, CERROR)
        addMessage(messages, _('Invalid regex: %s') % e, CERROR)

    # warn if not all examples could be extracted by the regex
    if len(examplesNotSeen) > 0:
        if edited:
            addMessage(messages, _('Your edited regex was unable to match all examples (e.g., %s).') % (", ".join(examplesNotSeen)), CWARN)
        else:
            if len(regex) > 0:
                addMessage(messages, _('The generated regex was unable to match all examples (e.g., %s).  Consider entering different examples, or manually editing the regex.') % (", ".join(examplesNotSeen)), CWARN)


    attributesAlreadyExtracted(fullevents, allextractions, args)
        

    outputextraction = ''

    sortedfields = allextractions.keys()
    sortedfields.sort()

    outputextractions = []

    if len(allextractions) == 0:
        outputextractions.append('<p class="empty">&lt;none&gt;</p>')
    else:
        for field in sortedfields:
            if len(sortedfields) > 1: # if more than one field, let's give it a name
                outputextractions.append("<h4>%s</h4>\n" % su.escape(field))
            outputextractions.append('<ul class="rulesetList">\n')
            terms = allextractions[field]
            for term in terms:
                if edited:
                    outputextractions.append('<li><span>%s</span></li>\n' % su.escape(term))
                else:
                    outputextractions.append('<li><a href="#" class="term" term="%s" title="Remove this term"><img src="/static/img/skins/default/a.gif" /></a><span>%s</span></li>\n' % (su.escape(term), su.escape(term)))
            outputextractions.append('</ul>\n')


    if len(counterexamples) > 0:
        outputextractions.append("<h4>Incorrect extractions</h4>\n")
        #outputextractions.append('<p class="help">To adjust results, add an extraction back to the Sample extractions list.</p>')
        outputextractions.append('<ul class="rulesetList">\n')
        for x in counterexamples:
            outputextractions.append('<li class="excluded"><a href="#" class="badterm" term="%s" title="Use this term"><img src="/static/img/skins/default/a.gif" /></a><span>%s</span></li>\n' % (su.escape(x),su.escape(x)))
        outputextractions.append('</ul>')

    outputextractions = ''.join(outputextractions)


    if len(messages) == 0 and regex != "" and not edited:
            addMessage(args, _('A regex has been successfully learned. Validate its correctness by reviewing the Sample extractions, or running Test. To improve results, add more examples and remove incorrect extractions.'), CMSG)


    # generate HTML element for 'restrict to'
    restrictionDropDown = []
    # if current restriction isn't a valid option, use last restriction (most specific)
    if restriction not in restrictionvalues:
        if len(restrictionvalues) > 0:
            restriction = restrictionvalues[-1]
    for item in restrictionvalues:
        escItem = su.escape(item)
        if item == restriction:
            restrictionDropDown.append('<option selected="selected">%s</option>' % escItem)
        else:
            restrictionDropDown.append('<option>%s</option>' % escItem)

    # sort warnings before messages. weak.
    messages.sort(errorCMP)
    messages.reverse()

    templateArgs = {
        'namespace'        : namespace,
        'eventtypeoptions' : ''.join(restrictionDropDown), # raw
        'counterexamples'  : _STRING_DELIMITER.join(args['counterexamples']),
        'events'           : outputevents,
        'examples'         : _STRING_DELIMITER.join(args['examples']),
        'message'          : _STRING_DELIMITER.join(messages),
        'sampleevent'      : eventraw,
        'sid'              : sid,
        'soffset'          : soffset,
        'search'           : search,
        'oldsearch'        : oldsearch,
        'regex'            : regex,
        'edited'           : args['edited'],
        'extractions'      : outputextractions,
        'testingurl'       : testingurl,
        'successmessage'   : successmessage
    }
    return templateArgs

 #.ugettext(message)
def unit_test():
    class FakeSession(dict):
        id = 5
    sessionKey = splunk.auth.getSessionKey('admin', 'changeme')
    #sessionKey = splunk.auth.getSessionKey('power', 'power')
    #sessionKey = splunk.auth.getSessionKey('user', 'user')
    try:
        cherrypy.session['sessionKey'] = sessionKey
    except AttributeError:
        setattr(cherrypy, 'session', FakeSession())
        cherrypy.session['sessionKey'] = sessionKey
    cherrypy.session['user'] = { 'name': 'admin' } #power, admin
    cherrypy.session['id'] = 12345
    cherrypy.config['module_dir'] = '/'
    cherrypy.config['build_number'] = '123'
    cherrypy.request.lang = 'en-US'
    # roflcon
    class elvis:
        def ugettext(self, msg):
            return msg
    cherrypy.request.t = elvis()
    # END roflcon

    ifxer = IFXController()

    argc = len(sys.argv)
    if argc == 3:
        search = sys.argv[1]
        example = sys.argv[2]
        print "search: '%s' example: '%s'" % (search, example)
        out = ifxer.index(search="index=main %s" % search, fieldname='pid', examples=example, save='true')
        #out = ifxer.index(search="index=main %s" % search, fieldname='pid', examples=example, save='true')
        print out
    else:
        print 'Usage: %s "restriction" "example"' % sys.argv[0]


    # print ifxer.index(sid=5, offset=0, fieldname='pid', examples='error', counterexamples='12321321', saved='false')
    ##     samplesearch = 'index=main sourcetype=foo'
    ##     regex = '(?P<foo>\w+) (?P<bar>\w+)'
    ##     fieldslist = 'foo,bar'
    ##     print "URL", ifxer.make_url('/search/app/search/flashtimeline',
    ##          _qs=[('q', 'search %s | regex "%s" | fields %s | dedup %s' % (samplesearch, regex, fieldslist, fieldslist))])


if __name__ == '__main__':
    unit_test()
