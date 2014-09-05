from drilldown import parseDrilldownAction
import lxml.etree as et
from validation_helper import WarningsCollector
import splunk.util
from panelElement import *
from row import Row
from panel import Panel
from dashboard import SimpleDashboard
import forminput
from base import *
from drilldown import parseDrilldown
import json
import logging
import re

logger = logging.getLogger('splunk.models.view_escaping')

ID_PATTERN = re.compile(r'^[a-z]\w*$', re.IGNORECASE)


def getValidationMessages(dashboardNode, viewName=None, digest=None, sourceApp=None):
    logger.info('Validating dashboard XML for view=%s', viewName)
    collector = WarningsCollector(logger=logger)
    try:
        with collector:
            createDashboardFromXml(dashboardNode, viewName, digest, sourceApp)
    except:
        pass
    return collector.getMessages()


def createDashboardFromXml(dashboardNode, viewName=None, digest=None, sourceApp=None):
    """
    @param dashboardNode: lxml node representing a dashboard or form
    @param viewName: the name of the xml file
    @param digest: boolean
    @return:
    """

    logger.info("Parsing view: simplexml=%s" % viewName)
    dashboard = SimpleDashboard(viewName=viewName, digest=digest, sourceApp=sourceApp)

    # Parse global options
    dashboard.label = dashboardNode.findtext('./label')
    dashboard.description = dashboardNode.findtext('./description')

    dashboard.customScript = dashboardNode.get('script', None)
    dashboard.customStylesheet = dashboardNode.get('stylesheet', None)
    dashboard.onUnloadCancelJobs = normalizeBoolean(
        dashboardNode.get('onunloadCancelJobs', dashboard.onUnloadCancelJobs))
    # master search template
    dashboard.searchTemplate = dashboardNode.findtext('./searchTemplate')
    dashboard.searchEarliestTime = dashboardNode.findtext('./earliestTime')
    dashboard.searchLatestTime = dashboardNode.findtext('./latestTime')
    dashboard.statusBuckets = 0

    dashboard.matchTagName = dashboardNode.tag
    if dashboard.matchTagName not in ['form', 'dashboard']:
        raise Exception(_('Invalid root element'))

    if dashboardNode.tag == 'form':
        # update the fieldset
        fieldsetNode = dashboardNode.find('./fieldset')
        if fieldsetNode is not None:
            dashboard.autoRun = splunk.util.normalizeBoolean(
                fieldsetNode.get('autoRun', False))
            dashboard.submitButton = splunk.util.normalizeBoolean(
                fieldsetNode.get('submitButton', True))

            for item in fieldsetNode:
                logger.debug("Found new element in fieldset: form=%s item=%s" % (viewName, item.tag))
                if item.tag == 'html':
                    panelInstance = createPanelElementFromXml(item)
                    dashboard.fieldset.append(panelInstance)
                elif item.tag == 'input':
                    inputDefaults = dict()
                    if not dashboard.submitButton:
                        inputDefaults['searchWhenChanged'] = True
                    inputInstance = forminput.createInput(item.get('type'), inputDefaults)
                    inputInstance.fromXml(item, sourceApp)
                    dashboard.fieldset.append(inputInstance)

    # set core view attributes
    for k in dashboard.standardAttributeMap:
        v = dashboardNode.get(k)
        if v is not None:
            if k in dashboard.booleanAttributeKeys:
                v = splunk.util.normalizeBoolean(v)
            elif k in dashboard.integerAttributeKeys:
                try:
                    v = int(v)
                except:
                    msg = "Key, %s, should have an integer value. Value found, %s" % (k, v)
                    logger.error(msg)
                    raise Exception(msg)
            setattr(dashboard, k, v)

    for rowNode in dashboardNode.findall('row'):
        logger.debug("Appending new row to view=%s" % viewName)
        dashboard.rows.append(createRowFromXml(rowNode, sourceApp))

    for row in dashboard.rows:
        for panel in row.panels:
            for panelElement in panel.panelElements:
                if hasattr(panelElement, 'noSearch') and panelElement.noSearch and dashboard.searchTemplate:
                    panelElement.searchMode = None
                    panelElement.searchCommand = None

                    # If this panel is an event, and it is tied to the global search template, then
                    # we need to tell that template to have status buckets
                    if isinstance(panelElement, Event):
                        dashboard.statusBuckets = 300

                if isinstance(panelElement, Event):
                    panelElement.statusBuckets = 300

                if hasattr(panelElement,
                           'searchMode') and panelElement.searchMode and panelElement.searchMode == POST_SEARCH_MODE:
                    dashboard.statusBuckets = 300

    normalizeIdentifiers(dashboard)
    return dashboard


def normalizeIdentifiers(dashboard):
    """
    Ensure all dashboard elements have an unique id

    @param dashboard: Dashboard object
    @return: no return value
    """
    seen = set()
    for el in dashboard.all_elements():
        if el.id is not None:
            if el.id in seen:
                raise Exception(_('Duplicate panel element ID "%s"') % el.id)
            if not ID_PATTERN.match(el.id):
                raise Exception(_(
                    'ID "%s" for panel element does not match pattern %s ' +
                    '(ID has to begin with a letter and must not '
                    'container characters other than letters, numbers and "_")') % (el.id, ID_PATTERN.pattern))
            seen.add(el.id)
    for el in dashboard.all_fields():
        if el.id is not None:
            if el.id in seen:
                raise Exception(_('Duplicate input field ID "%s"') % el.id)
            if not ID_PATTERN.match(el.id):
                raise Exception(_(
                    'ID "%s" for input field does not match pattern %s ' +
                    '(ID has to begin with a letter and must not '
                    'container characters other than letters, numbers and "_"') % (el.id, ID_PATTERN.pattern))
            seen.add(el.id)
    panelIndex = 1
    ctxId = 1
    fieldId = 1
    globalSearch = None
    if getattr(dashboard, 'searchTemplate', None) is not None:
        dashboard.context = globalSearch = "search%d" % ctxId
        ctxId += 1

    for el in dashboard.all_elements():
        if el.id is None:
            while True:
                el.id = 'element%d' % panelIndex
                panelIndex += 1
                if not el.id in seen:
                    break
        if el.context is None:
            if getattr(el, 'searchMode', None):
                el.context = "search%d" % ctxId
                ctxId += 1
            elif globalSearch is not None:
                el.context = globalSearch
    for field in dashboard.all_fields():
        if field.id is None:
            while True:
                field.id = 'field%d' % fieldId
                fieldId += 1
                if not field.id in seen:
                    break
        if getattr(field, 'context', None) is None:
            if getattr(field, 'search', None) or getattr(field, 'savedSearch', None):
                field.context = "search%d" % ctxId
                ctxId += 1


def createRowFromXml(rowNode, sourceApp=None):
    """
    Parses a row xml node
    @param rowNode: Lxml representing a form or dashboard element
    @return:
    """
    logger.debug("parsing dashboard row node")
    if rowNode.get('grouping'):
        rowGroupings = map(
            int,
            rowNode.get('grouping').replace(' ', '').strip(',').split(','))
        logger.debug("Found row grouping=%s" % rowGroupings)
    else:
        rowGroupings = None

    row = Row(rowGroupings)

    if len(rowNode) is 0:
        logger.warn('Dashboard row is empty (line %d)', rowNode.sourceline)

    else:
        hasPanels = False
        hasVisualizations = False
        for panelElementNode in rowNode:
            if panelElementNode.tag == "panel":
                if hasVisualizations:
                    raise Exception(_('Row, on line=%s, should not combine visualizations and panels. Panel, on line=%s') % (rowNode.sourceline, panelElementNode.sourceline))
                hasPanels = True
                row.panels.append(createPanelFromXML(panelElementNode, sourceApp))
            elif panelElementNode.tag == et.Comment:
                continue
            else:
                if hasPanels:
                    raise Exception(_('Row, on line=%s, should not combine visualizations and panels. Visualization, on line=%s') % (rowNode.sourceline, panelElementNode.sourceline))
                hasVisualizations = True
                try:
                    panelElement = createPanelElementFromXml(panelElementNode)
                    if panelElement:
                        row.appendPanelElement(panelElement)
                except NotImplementedError:
                    raise Exception(_('Row, on line=%s, conains unknown node=%s on line=%s.') % (rowNode.sourceline, panelElementNode.tag, panelElementNode.sourceline))
    return row


def createPanelFromXML(panelNode, sourceApp=None):
    panel = Panel(None)

    if len(panelNode) is 0:
        logger.warn('Dashboard panel is empty (line %d)', panelNode.sourceline)

    for panelElementNode in panelNode:
        if panelElementNode.tag == 'input':
            inputInstance = forminput.createInput(
                panelElementNode.get('type'), dict(searchWhenChanged=True))
            inputInstance.fromXml(panelElementNode, sourceApp)
            panel.fieldset.append(inputInstance)
        else:
            panelElement = createPanelElementFromXml(panelElementNode)
            if panelElement:
                panel.appendPanelElement(panelElement)
    return panel


def getTokenDependencies(node):
    tokenDependencies = dict()
    if 'depends' in node.attrib:
        tokenDependencies['depends'] = node.attrib.get('depends', None)
    if 'rejects' in node.attrib:
        tokenDependencies['rejects'] = node.attrib.get('rejects', None)
    logger.info('Found token dependencies for <%s id="%s">: %s', node.tag, node.attrib.get('id', '-'),
                tokenDependencies)
    return tokenDependencies if len(tokenDependencies) > 0 else None


def createPanelElementFromXml(panelElementNode):
    def createHtmlPanelElementFromXml(panelElementNode, panelInstance):
        """
        Override default parser and just get the text
        """
        logger.debug("parsing html panel element")
        src = panelElementNode.get('src')
        if src:
            panelInstance.options['serverSideInclude'] = src
            return

        flatString = et.tostring(panelElementNode)
        flatString = flatString.replace("<html>", "").replace("</html>", "").strip()
        panelInstance.options['rawcontent'] = flatString
        panelInstance.tokenDependencies = getTokenDependencies(panelElementNode)

    def createChartPanelElementFromXml(node, element):
        createDefaultPanelElementFromXml(node, element)
        selectionNode = node.find('selection')
        if selectionNode:
            element.selection = []
            for actionNode in [node for node in selectionNode if et.iselement(node) and type(node.tag) is str]:
                action = parseDrilldownAction(actionNode)
                if action:
                    element.selection.append(action)

    def createTablePanelElementFromXml(panelElementNode, panelInstance):
        """
        Add a format tag to provide cell formatting
        (primarily for sparklines at the current time)
        Each format tag may have some option sub-tags
        Each option may contain list or option tags generating
        lists or dictionaries respectively

        Each format tag may specify a field to filter on
        (defaults to all fields) and a type to apply (eg 'sparkline')
        """
        logger.debug("parsing table panel element")

        def parseOption(node):
            """Extract nested options/lists"""
            listNodes = node.findall('list')
            optionNodes = node.findall('option')

            if listNodes and optionNodes:
                raise ValueError("Tag cannot contain both list and option subtags")
            elif listNodes:
                result = []
                for listNode in listNodes:
                    result.append(parseOption(listNode))
                return result
            elif optionNodes:
                result = {}
                for optionNode in optionNodes:
                    result[optionNode.get('name')] = parseOption(optionNode)
                return result
            else:
                return node.text

        createDefaultPanelElementFromXml(panelElementNode, panelInstance)
        fieldFormats = {}
        for formatNode in panelElementNode.findall('format'):
            logger.debug("Parsing format view node")
            field = formatNode.get('field', '*')
            formatType = formatNode.get('type', 'text')
            options = {}
            for optionNode in formatNode.findall('option'):
                options[optionNode.get('name')] = parseOption(optionNode)
            fieldFormats.setdefault(field, []).append({
                'type': formatType,
                'options': options
            })
        panelInstance.fieldFormats = fieldFormats

    def createDefaultPanelElementFromXml(panelElementNode, panelInstance):
        logger.debug("Parsing default panel element options")
        # define common XML node -> object property mappings
        commonNodeMap = [
            ('title', 'title'),
            ('earliestTime', 'searchEarliestTime'),
            ('latestTime', 'searchLatestTime')
        ]

        # define search mode XML node -> object property mappings
        searchModeNodeMap = [
            ('searchString', TEMPLATE_SEARCH_MODE),
            ('searchName', SAVED_SEARCH_MODE),
            ('searchTemplate', TEMPLATE_SEARCH_MODE),
            ('searchPostProcess', POST_SEARCH_MODE)
        ]
        for nodeName, memberName in commonNodeMap:
            val = panelElementNode.findtext(nodeName)
            if val is not None:
                setattr(panelInstance, memberName, val)

        optionTypeMap = {}
        if hasattr(panelInstance.__class__, 'optionTypeMap'):
            optionTypeMap = getattr(panelInstance.__class__, 'optionTypeMap')

        # option params get their own container
        for node in panelElementNode.findall('option'):
            optionName = node.get('name')
            optionValue = node.text
            if optionName in optionTypeMap:
                optionValue = optionTypeMap[optionName](optionValue)
            if isinstance(optionValue, str) and optionValue != None:
                optionValue = optionValue.strip()
            panelInstance.options[optionName] = optionValue

        # handle different search modes
        if getattr(panelInstance.__class__, 'hasSearch'):
            foundSearch = False
            for pair in searchModeNodeMap:
                if panelElementNode.find(pair[0]) is not None:
                    foundSearch = True
                    panelInstance.searchMode = pair[1]
                    panelInstance.searchCommand = (
                        panelElementNode.findtext(pair[0])).replace("\n", " ")
                    break
            if not foundSearch:
                panelInstance.searchMode = TEMPLATE_SEARCH_MODE
                panelInstance.searchCommand = ''
                panelInstance.noSearch = True

        # handle field lists
        if panelElementNode.find('fields') is not None:
            fields = panelElementNode.findtext('fields').strip()
            if len(fields) and fields[0] == '[' and fields[-1] == ']':
                panelInstance.searchFieldList = json.loads(fields)
            else:
                panelInstance.searchFieldList = splunk.util.stringToFieldList(fields)

        # extract simple XML drilldown params
        panelInstance.simpleDrilldown = parseDrilldown(panelElementNode.find('drilldown'))

        panelInstance.tokenDependencies = getTokenDependencies(panelElementNode)

        # extract the contents of all top-level comment nodes
        for node in panelElementNode.xpath('./comment()'):
            panelInstance.comments.append(node.text)

        # extract the comments from inside the drilldown tag
        for node in panelElementNode.xpath('./drilldown/comment()'):
            panelInstance.drilldownComments.append(node.text)

    def createPanel(name):
        """
        Factory method for creating an appropriate panel object based upon the
        name.  Returns an instance of a BasePanel subclass, or throws a
        NotImplementedError if no suitable mapper is found.

        This method works by inspecting all objects that subclass BasePanel and
        attempting to match their matchTagName class attribute.
        """

        if not name:
            raise ValueError('Cannot create panel from nothing')

        for key, obj in globals().items():
            try:
                if issubclass(obj, BasePanel) and name == obj.matchTagName:
                    #  only Chart objects need to be instantiated
                    if obj is Chart:
                        return Chart()
                    else:
                        return obj()
            except:
                pass
        raise NotImplementedError(
            _('Cannot find object mapper for panel type: %s') % name)

    if not isinstance(panelElementNode.tag, basestring):
        return False
    panelType = panelElementNode.tag
    panelInstance = createPanel(panelType)

    id = panelElementNode.attrib.get('id')
    if id is not None:
        panelInstance.id = id

    logger.debug("found panel element type=%s" % panelType)
    if panelType == 'table':
        createTablePanelElementFromXml(panelElementNode, panelInstance)
    elif panelType == 'chart':
        createChartPanelElementFromXml(panelElementNode, panelInstance)
    elif panelType == 'html':
        createHtmlPanelElementFromXml(
            panelElementNode, panelInstance)
    else:
        createDefaultPanelElementFromXml(panelElementNode, panelInstance)
    return panelInstance


if __name__ == '__main__':
    import unittest

    def getRowXml(args='', panels=1):
        nodes = ['<row %(args)s>']
        for i in range(0, panels):
            nodes.append('<single></single>')
        nodes.append('</row>')
        xml = ''.join(nodes)
        return xml % {'args': args}

    def getPanelElementXml(type="foo", options=None, args=None):
        options = options or (
            '<searchString> | metadata type="sources" | '
            'stats count</searchString>')
        args = args or ''
        xml = '''
            <%(type)s %(args)s>
                %(options)s
            </%(type)s>
        '''
        return xml % {'type': type, 'options': options, 'args': args}

    class CreatePanelElementTests(unittest.TestCase):

        def createPanel(self, type="foo", options=None, args=None):
            xml = getPanelElementXml(type, options, args)
            root = et.fromstring(xml)
            return createPanelElementFromXml(root)

        def testCreateUnknownPanel(self):
            with self.assertRaises(NotImplementedError):
                d = self.createPanel('foo')

        def testCreateAllowedPanels(self):
            for panelType in ['single', 'chart', 'table',
                              'html', 'map', 'event', 'list']:
                d = self.createPanel(panelType)
                self.assertTrue(d.matchTagName == panelType)

        def testCreateHTMLPanel(self):
            d = self.createPanel(
                'html', args='src="/foo/bar"')
            self.assertTrue(d.options.get('serverSideInclude') == '/foo/bar')
            self.assertFalse(d.options.get('rawcontent'))
            d = self.createPanel(
                'html', options='<div>Test</div>', args='src="/foo/bar"')
            self.assertTrue(d.options.get('serverSideInclude') == '/foo/bar')
            self.assertFalse(d.options.get('rawcontent'))
            d = self.createPanel(
                'html', options='<div>Test</div>')
            self.assertFalse(d.options.get('serverSideInclude'))
            self.assertTrue(d.options.get('rawcontent') == '<div>Test</div>')

        def testCreateTablePanel(self):
            """tables only have special format fields"""
            d = self.createPanel('table', options='''
                <format>
                    <option name="fff">
                        <list>foo</list>
                        <list>bop</list>
                    </option>
                    <option name="bippity">
                        <option name="bippity">bop</option>
                    </option>
                </format>
                <format field="foobar" type="num">
                    <option name="fff">
                        <list>foo</list>
                        <list>bop</list>
                    </option>
                    <option>bar</option>
                </format>
                ''')
            self.assertTrue(d.fieldFormats == {
                '*': [{'type': 'text',
                       'options': {'bippity': {'bippity': 'bop'},
                                   'fff': ['foo', 'bop']
                       }
                      }],
                'foobar': [{'type': 'num',
                            'options': {None: 'bar',
                                        'fff': ['foo', 'bop']
                            }
                           }]
            })
            #  formats can't mix options and lists.
            #  lists can contain options and options can contain list but
            #     neither can contain both.
            with self.assertRaises(ValueError):
                d = self.createPanel(
                    'table',
                    options='''
                        <format>
                            <option name="fff">
                                <list>foo</list>
                                <list>bop</list>
                                <option name="should">not work</option>
                            </option>
                            <option>bar</option>
                        </format>
                    ''')

        def testCreateChartPanelWithSelection(self):
            chart = self.createPanel('chart', options='''
                <selection>
                    <set token="foo">$start$</set>
                    <unset token="bar" />
                </selection>
                ''')

            self.assertIsNotNone(chart.selection)
            self.assertEqual(2, len(chart.selection))
            self.assertEqual("settoken", chart.selection[0].type)
            self.assertEqual("unsettoken", chart.selection[1].type)


        def testCreateDefaultPanel(self):
            """All panels have some things in common"""
            #s test common nodes
            d = self.createPanel('single', options='''
                <title>Title1</title>
                <earliestTime>0</earliestTime>
                <latestTime>50</latestTime>
                <fields>foo bar baz</fields>
                ''')
            self.assertEqual(d.searchEarliestTime, '0')
            self.assertEqual(d.searchLatestTime, '50')
            self.assertEqual(d.title, 'Title1')
            self.assertEqual(d.searchFieldList, 'foo bar baz'.split())

            # should be able to accept one of the search modes
            d = self.createPanel('single', options='''
                <searchString>search string</searchString>
                ''')
            self.assertEqual(getattr(d, 'searchMode'), 'template')
            self.assertEqual(getattr(d, 'searchCommand'), 'search string')
            d = self.createPanel('single', options='''
                <searchName>search saved</searchName>
                <searchTemplate>search template</searchTemplate>
                <searchPostProcess>search postsearch</searchPostProcess>
                ''')
            self.assertEqual(getattr(d, 'searchMode'), 'saved')
            self.assertEqual(getattr(d, 'searchCommand'), 'search saved')
            d = self.createPanel('single', options='''
                <searchTemplate>search template</searchTemplate>
                ''')
            self.assertEqual(getattr(d, 'searchMode'), 'template')
            self.assertEqual(getattr(d, 'searchCommand'), 'search template')
            d = self.createPanel('single', options='''
                <searchPostProcess>search postsearch</searchPostProcess>
                ''')
            self.assertEqual(getattr(d, 'searchMode'), 'postsearch')
            self.assertEqual(getattr(d, 'searchCommand'), 'search postsearch')

            # any option show be saved into a dictionary
            optionsDict = {'f': ' foo', 'b': 'bar', 'z': 'zip'}
            options = ''
            for k, v in optionsDict.iteritems():
                options += '<option name="%s">%s</option>' % (k, v)
            d = self.createPanel('single', options=options)
            self.assertEqual(d.options['f'], optionsDict['f'].strip())
            self.assertEqual(d.options['b'], optionsDict['b'].strip())
            self.assertEqual(d.options['z'], optionsDict['z'].strip())

        def testTokenDependencies(self):
            for panelType in ('table', 'chart', 'single', 'map', 'list', 'html'):
                panel = createPanelElementFromXml(et.fromstring('''
                    <%(type)s depends="$foo$">
                    </%(type)s>
                ''' % dict(type=panelType)))
                self.assertIsNotNone(panel)
                self.assertIsNotNone(panel.tokenDependencies)
                self.assertEquals(len(panel.tokenDependencies), 1)
                self.assertTrue('depends' in panel.tokenDependencies)
                self.assertEquals(panel.tokenDependencies['depends'], '$foo$')

                panel = createPanelElementFromXml(et.fromstring('''
                    <%(type)s rejects="$foo$">
                    </%(type)s>
                ''' % dict(type=panelType)))
                self.assertIsNotNone(panel)
                self.assertIsNotNone(panel.tokenDependencies)
                self.assertEquals(len(panel.tokenDependencies), 1)
                self.assertTrue('rejects' in panel.tokenDependencies)
                self.assertEquals(panel.tokenDependencies['rejects'], '$foo$')

                panel = createPanelElementFromXml(et.fromstring('''
                    <%(type)s id="foo" depends="$foo$" rejects="$bar$">
                    </%(type)s>
                ''' % dict(type=panelType)))
                self.assertIsNotNone(panel)
                self.assertIsNotNone(panel.tokenDependencies)
                self.assertEquals(len(panel.tokenDependencies), 2)
                self.assertTrue('depends' in panel.tokenDependencies)
                self.assertTrue('rejects' in panel.tokenDependencies)
                self.assertEquals(panel.tokenDependencies['depends'], '$foo$')
                self.assertEquals(panel.tokenDependencies['rejects'], '$bar$')

                panel = createPanelElementFromXml(et.fromstring('''
                    <%(type)s>
                    </%(type)s>
                ''' % dict(type=panelType)))
                self.assertIsNotNone(panel)
                self.assertIsNone(panel.tokenDependencies)

        def testSimpleDrilldownPopulated(self):
            for panelType in ('table', 'chart', 'single', 'map', 'list'):
                xmlNode = et.fromstring('''
                    <%(type)s id="panel1">
                        <title>Panel 1</title>
                        <drilldown>
                            <set token="foobar">($click.value$)</set>
                        </drilldown>
                    </%(type)s>
                ''' % dict(type=panelType))
                panel = createPanelElementFromXml(xmlNode)
                self.assertIsNotNone(panel)
                self.assertEquals(len(panel.simpleDrilldown), 1)

    class CreateRowTests(unittest.TestCase):
        def getRowLxml(self, args='', panels=1):
            xml = getRowXml(args, panels)
            root = et.fromstring(xml)
            return createRowFromXml(root)

        def testCreateRow(self):
            d = self.getRowLxml()
            self.assertTrue(d)
            self.assertEqual(len(d.panels), 1)
            self.assertEqual(
                d.panels[0].panelElements[0].matchTagName, 'single')

        def testRowGrouping(self):
            d = self.getRowLxml(args='grouping="2,1"', panels=3)
            self.assertTrue(d)
            self.assertEqual(len(d.panels), 2)
            self.assertEqual(len(d.panels[0].panelElements), 2)
            self.assertEqual(len(d.panels[1].panelElements), 1)

        def testCreateRowWith3Panels(self):
            d = self.getRowLxml(args='', panels=3)
            self.assertTrue(d)
            self.assertEqual(len(d.panels), 3)

        def testCreateRowWithPanels(self):
            xml = '''
                    <row>
                        <panel>
                            <single/>
                        </panel>
                    </row>
                '''
            root = et.fromstring(xml)
            d =  createRowFromXml(root)
            self.assertTrue(d)
            self.assertEqual(len(d.panels), 1)
            self.assertEqual(
                d.panels[0].panelElements[0].matchTagName, 'single')

        def testRowGroupingWithPanels(self):
            xml = '''
                    <row>
                        <panel>
                            <single/>
                            <single/>
                        </panel>
                        <panel>
                            <single/>
                        </panel>
                    </row>
                '''
            root = et.fromstring(xml)
            d =  createRowFromXml(root)
            self.assertTrue(d)
            self.assertEqual(len(d.panels), 2)
            self.assertEqual(len(d.panels[0].panelElements), 2)
            self.assertEqual(len(d.panels[1].panelElements), 1)

        def testCreateRowWithComments(self):
            xml = '''
                    <row>
                        <!-- this better work -->
                        <panel/>
                    </row>
                '''
            root = et.fromstring(xml)
            row =  createRowFromXml(root)
            xml = '''
                    <row>
                        <!-- this better work -->
                        <chart/>
                    </row>
                '''
            root = et.fromstring(xml)
            row =  createRowFromXml(root)

        def testCreateRowWithTitleException(self):
            with self.assertRaises(Exception):
                xml = '''
                        <row>
                            <title/>
                            <panel/>
                        </row>
                    '''
                root = et.fromstring(xml)
                row =  createRowFromXml(root)
            with self.assertRaises(Exception):
                xml = '''
                        <row>
                            <title/>
                            <chart/>
                        </row>
                    '''
                root = et.fromstring(xml)
                row =  createRowFromXml(root)


    class CreateDashboardTests(unittest.TestCase):
        def getSimpleLxml(self, root='dashboard', rows=1, fieldset=''):
            nodes = []
            nodes.append('<%(root)s>')
            nodes.append(fieldset)
            for i in range(0, rows):
                nodes.append(getRowXml())
            nodes.append('</%(root)s>')
            xml = ''.join(nodes)
            xml = xml % {'root': root}
            root = et.fromstring(xml)
            return createDashboardFromXml(root)

        def testCreateDashboard(self):
            d = self.getSimpleLxml()
            self.assertTrue(d)
            self.assertEqual(d.matchTagName, 'dashboard')

        def testCreateForm(self):
            d = self.getSimpleLxml(root='form')
            self.assertTrue(d)
            self.assertEqual(d.matchTagName, 'form')

        def testCreateFormWithFieldset(self):
            fieldset = '''
            <fieldset>
                <input token="foo" searchWhenChanged="True"></input>
                <html></html>
                <shouldntShow></shouldntShow>
            </fieldset>
            '''
            d = self.getSimpleLxml(root='form', fieldset=fieldset)
            self.assertTrue(d)
            self.assertTrue(d.fieldset)
            self.assertEqual(len(d.fieldset), 2)
            self.assertEqual(d.fieldset[0].__class__.__name__, 'TextInput')
            self.assertEqual(d.fieldset[0].searchWhenChanged, True)
            self.assertEqual(d.fieldset[1].matchTagName, 'html')
            self.assertEqual(d.matchTagName, 'form')

        def testCreateUnsupportedRoot(self):
            with self.assertRaises(Exception):
                self.getSimpleLxml(root='notFormOrDashboard')

        def testValidationMessages(self):
            msgs = getValidationMessages(et.fromstring('<dashboard></dashboard>'))
            self.assertIsNotNone(msgs)
            self.assertEquals(len(msgs), 0)

            msgs = getValidationMessages(et.fromstring('''
                <dashboard>
                    <row>
                        <table>
                            <drilldown>
                                <set token="foo">...</set>
                                <condition field="bar"></condition>
                            </drilldown>
                        </table>
                    </row>
                </dashboard>
            '''))
            self.assertIsNotNone(msgs)
            self.assertGreater(len(msgs), 0)

            msgs = getValidationMessages(et.fromstring('''
                <dashboard>
                    <row>
                        <table>
                            <drilldown>
                                <set field="bar" token="foo">...</set>
                            </drilldown>
                        </table>
                    </row>
                </dashboard>
            '''))
            self.assertIsNotNone(msgs)
            self.assertGreater(len(msgs), 0)

            msgs = getValidationMessages(et.fromstring('''
                <dashboard>
                    <row>
                        <table>
                            <drilldown>
                                <link field="bar">...</link>
                                <link field="bar">...</link>
                            </drilldown>
                        </table>
                    </row>
                </dashboard>
            '''))
            self.assertIsNotNone(msgs)
            self.assertGreater(len(msgs), 0)

            msgs = getValidationMessages(et.fromstring('''
                <dashboard>
                    <row>
                    </row>
                </dashboard>
            '''))
            self.assertIsNotNone(msgs)
            self.assertGreater(len(msgs), 0)

            msgs = getValidationMessages(et.fromstring('<foobar></foobar>'))
            self.assertIsNotNone(msgs)
            self.assertGreater(len(msgs), 0)

    loader = unittest.TestLoader()
    unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([
        loader.loadTestsFromTestCase(CreatePanelElementTests),
        loader.loadTestsFromTestCase(CreateRowTests),
        loader.loadTestsFromTestCase(CreateDashboardTests)
    ]))
