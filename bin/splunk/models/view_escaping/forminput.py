import base
import splunk.util
import logging
import inspect
from splunk.appserver.mrsparkle.lib import times
import StringIO
import csv

logger = logging.getLogger('splunk.models.legacy_views.forminput')


def createInput(name, defaults):
    '''
    Factory method for creating an appropriate input object based upon the
    matchTypeName.  Returns an instance of a BaseInput subclass, or throws a
    NotImplementedError if no suitable mapper is found.

    This method works by inspecting all objects that subclcass BaseInput and
    attempting to match their matchTagName class attribute.
    '''

    # set default as text box
    if name is None:
        return TextInput(defaults)

    for key, obj in globals().items():
        if inspect.isclass(obj) and issubclass(obj, BaseInput) and key[-5:] == 'Input':
            if hasattr(obj, 'matchTagName') and name == obj.matchTagName:
                return obj(defaults)
    raise NotImplementedError(
        'Cannot find object mapper for input type: %s' % name)


class BaseInput(object):
    '''
    Represents the base class for all form search input view objects.  These
    objects are used in constructing a search to dispatch to splunkd.  All
    input objects can be set statically, and some input objects can be
    dynamically populated at runtime.
    '''


    def __init__(self, defaults={}):

        self.token = None
        self.label = None
        self.defaultValue = None
        self.seedValue = None
        self.prefixValue = None
        self.suffixValue = None
        self.commonNodeMap = [
            ('label', 'label'),
            ('default', 'defaultValue'),
            ('seed', 'seedValue'),
            ('prefix', 'prefixValue'),
            ('suffix', 'suffixValue'),
            ('searchName', 'searchCommand')
        ]

        # init standard search configuration params
        self.searchMode = base.SAVED_SEARCH_MODE
        self.searchCommand = None

        self.searchWhenChanged = defaults['searchWhenChanged'] if 'searchWhenChanged' in defaults else None

        self.options = {}
        self.id = None

    def fromXml(self, lxmlNode, sourceApp):

        self.token = lxmlNode.get('token')

        for pair in self.commonNodeMap:
            setattr(self, pair[1], lxmlNode.findtext(pair[0]))

        if self.label is None:
            self.label = self.token

        self.searchWhenChanged = splunk.util.normalizeBoolean(
            lxmlNode.get('searchWhenChanged', self.searchWhenChanged))


class TextInput(BaseInput):
    '''
    Represents a single text field input.
    '''
    matchTagName = 'text'


class InternalSearchInput(BaseInput):

    def __init__(self, defaults):
        BaseInput.__init__(self, defaults)

        self.localCommonNodeMap = [
            ('populatingSearch', 'search'),
            ('populatingSavedSearch', 'savedSearch')
        ]
        self.search = None
        self.savedSearch = None
        self.settingToCreate = None
        self.staticFields = []
        self.searchFields = []
        self.earliest_time = None
        self.latest_time = None
        self.selectFirstChoice = False

    def fromXml(self, lxmlNode, sourceApp):
        BaseInput.fromXml(self, lxmlNode, sourceApp)

        for item in lxmlNode.findall('choice'):
            value = item.get('value')
            staticField = {
                'label': item.text
            }
            if value != None:
                staticField['value'] = value
            else:
                staticField['value'] = item.text
            self.staticFields.append(staticField)

        for pair in self.localCommonNodeMap:
            if pair[0] == 'populatingSearch':
                node = lxmlNode.find(pair[0])
                if node is not None:
                    searchField = {
                        'label': node.get('fieldForLabel')
                    }
                    value = node.get('fieldForValue')
                    if value:
                        searchField['value'] = value
                    self.searchFields.append(searchField)

                    self.earliest_time = node.get('earliest')
                    self.latest_time = node.get('latest')
                    self.searchCommand = node.text.strip()

            elif pair[0] == 'populatingSavedSearch':
                node = lxmlNode.find(pair[0])
                if node is not None:
                    searchField = {
                        'label': node.get('fieldForLabel')
                    }
                    value = node.get('fieldForValue')
                    if value:
                        searchField['value'] = value
                    self.searchFields.append(searchField)
                    self.searchCommand = node.text.strip()

            setattr(self, pair[1], self.searchCommand)

        # SPL-64605 Normalize the default selection - prefers value over label
        if not self.searchCommand and self.defaultValue:
            found_default = False
            for choice in self.staticFields:
                if choice['value'] == self.defaultValue:
                    found_default = True
                    break
            if not found_default:
                for choice in self.staticFields:
                    if choice['label'] == self.defaultValue:
                        # Translate the label to its corresponding value
                        self.defaultValue = choice['value']
                        break

        # SPL-79171 allow the user to specify whether the first choice is selected by default
        selectFirstChoiceNode = lxmlNode.find('selectFirstChoice')
        if selectFirstChoiceNode is not None:
            try:
                self.selectFirstChoice = splunk.util.normalizeBoolean(selectFirstChoiceNode.text, enableStrictMode=True)
            except ValueError:
                logger.warn('Invalid boolean "%s" for selectFirstChoice', self.selectFirstChoice)
                self.selectFirstChoice = False

    def normalizedSearchCommand(self):
        return self.search.lstrip()


class DropdownInput(InternalSearchInput):
    '''
    Represents a select dropdown input.  This element can have its options
    populated via a saved search, or other entity list.
    '''

    matchTagName = 'dropdown'

    def __init__(self, defaults):
        InternalSearchInput.__init__(self, defaults)
        self.selected = None
        self.localCommonNodeMap.append(('default', 'selected'))


class RadioInput(InternalSearchInput):
    '''
    Represents a set of one or more radio button inputs.  This element
    can have its options populated via a saved search, or other entity list.
    '''
    matchTagName = 'radio'

    def __init__(self, defaults):
        InternalSearchInput.__init__(self, defaults)
        self.name = None
        self.checked = None
        self.localCommonNodeMap.append(('default', 'checked'))

    def fromXml(self, lxmlNode, sourceApp):
        InternalSearchInput.fromXml(self, lxmlNode, sourceApp)
        self.name = '_'.join([self.token, 'name'])


class TimeInput(BaseInput):
    '''
    Represents a timerange selection input.
    '''
    matchTagName = 'time'

    def __init__(self, defaults):
        BaseInput.__init__(self, defaults)
        self.selected = None
        self.label = None

    def fromXml(self, lxmlNode, sourceApp):
        BaseInput.fromXml(self, lxmlNode, sourceApp)
        self.searchWhenChanged = splunk.util.normalizeBoolean(lxmlNode.get('searchWhenChanged', self.searchWhenChanged))
        selected = lxmlNode.find('default')
        if selected is not None:
            et,lt = selected.find('earliestTime'), selected.find('latestTime')
            if et is not None or lt is not None:
                self.selected = dict(
                    earliestTime=et.text if et is not None else None,
                    latestTime=lt.text if lt is not None else None
                )
            elif selected.text:
                self.selected = selected.text.strip()
                appTimes = times.getTimeRanges(sourceApp)
                for time in appTimes:
                    if time['label'].strip() == self.selected:
                        self.selected = dict(
                            earliestTime=time.get('earliest_time', None),
                            latestTime=time.get('latest_time', None)
                        )
                        break
                else:
                    self.selected = dict(
                        earliestTime=0,
                        latestTime=None
                    )
            else:
                self.selected = dict(
                    earliestTime=0,
                    latestTime=None
                )
        label = lxmlNode.find('label')
        if label is not None:
            self.label = label.text


class MultiValueSearchInput(InternalSearchInput):
    """
    Represents a search input that will have an array as a value.
    <input type="multiselect" token="my_multiselect">
        <label> Choose Sourcetype:</label>
        <choice value="*">All</choice>
        <option name="prefix">q=[</option>
        <option name="suffix">]</option>
        <option name="value_prefix">sourcetype="</option>
        <option name="value_suffix">"</option>
        <option name="delimiter"> </option>
        <option name="minCount">1</option>
        <option name="showSelectAll">true</option>    <!-- Enable users to have quick select and deselect all links -->
        <option name="showDeselectAll">true</option>
        <option name="width">5</option>   <!-- width; allow users to configure width based on length of values and #  -->
        <populatingSearch fieldForLabel="sourcetype" fieldForValue="sourcetype" earliest="-24h" latest="now">index=_internal | stats count by sourcetype
        </populatingSearch>
        <default>NULL</default>            <!-- if default set to NULL, then submit token should be null -->
    </input>
    """

    def __init__(self, defaults):
        InternalSearchInput.__init__(self, defaults)
        self.selected = None
        self.label = None
        self.valuePrefix = ""
        self.valueSuffix = ""
        self.delimiter = " "
        self.minCount = None
        self.showSelectAl = False
        self.showDeselectAll = False
        self.width = None
        self.commonNodeMap.append(('default', 'selected'))
        self.commonNodeMap.append(('valuePrefix', 'valuePrefix'))
        self.commonNodeMap.append(('valueSuffix', 'valueSuffix'))
        self.commonNodeMap.append(('delimiter', 'delimiter'))
        self.commonNodeMap.append(('minCount', 'minCount'))
        self.commonNodeMap.append(('showSelectAll', 'showSelectAll'))
        self.commonNodeMap.append(('showDeselectAll', 'showDeselectAll'))
        self.commonNodeMap.append(('width', 'width'))

    def fromXml(self, lxmlNode, sourceApp):
        InternalSearchInput.fromXml(self, lxmlNode, sourceApp)
        defaultValue = getattr(self, 'defaultValue', None)
        if defaultValue is not None:
            reader = csv.reader(StringIO.StringIO(defaultValue.strip()), delimiter=',')
            values = [item.strip() for row in reader for item in row]
            if len(values):
                self.defaultValue = values


class MultiSelectInput(MultiValueSearchInput):
    """
    Represents a multiple selection input.
    """
    matchTagName = 'multiselect'


class CheckboxGroupInput(MultiValueSearchInput):
    """
    Represents a group of checkbox input.
    """
    matchTagName = 'checkbox'


if __name__ == '__main__':
    import unittest
    import lxml.etree as et

    nodeMap = [
        ('label', 'label'),
        ('default', 'defaultValue'),
        ('seed', 'seedValue'),
        ('prefix', 'prefixValue'),
        ('suffix', 'suffixValue'),
        ('searchName', 'searchCommand'),
        ('default', 'selected'),
        ('valuePrefix', 'valuePrefix'),
        ('valueSuffix', 'valueSuffix'),
        ('delimiter', 'delimiter'),
        ('minCount', 'minCount'),
        ('showSelectAll', 'showSelectAll'),
        ('showDeselectAll', 'showDeselectAll'),
        ('width', 'width')
    ]

    class MultiValueInputTests(unittest.TestCase):

        def testMultiSelectInput(self):
            multiSelectInput = MultiSelectInput(dict())
            self.assertItemsEqual(nodeMap, multiSelectInput.commonNodeMap)
            self.assertEqual("multiselect", multiSelectInput.matchTagName)

    class CheckboxInputTests(unittest.TestCase):

        def testCheckboxInput(self):
            checkboxGroupInput = CheckboxGroupInput(dict())
            self.assertItemsEqual(nodeMap, checkboxGroupInput.commonNodeMap)
            self.assertEqual("checkbox", checkboxGroupInput.matchTagName)

    class SelectFirstChoiceTests(unittest.TestCase):
        def testParseSelectFirstChoice(self):
            node = et.fromstring('<input type="dropdown" token="foo" />')
            item = createInput(node.attrib.get('type'), defaults=dict())
            item.fromXml(node, 'fake')
            self.assertFalse(item.selectFirstChoice)

            node = et.fromstring('<input type="dropdown" token="foo">'
                                 '<selectFirstChoice>true</selectFirstChoice>'
                                 '</input>')
            item = createInput(node.attrib.get('type'), defaults=dict())
            item.fromXml(node, 'fake')
            self.assertTrue(item.selectFirstChoice)

            node = et.fromstring('<input type="dropdown" token="foo">'
                                 '<selectFirstChoice>1</selectFirstChoice>'
                                 '</input>')
            item = createInput(node.attrib.get('type'), defaults=dict())
            item.fromXml(node, 'fake')
            self.assertTrue(item.selectFirstChoice)

            node = et.fromstring('<input type="dropdown" token="foo">'
                                 '<selectFirstChoice>0</selectFirstChoice>'
                                 '</input>')
            item = createInput(node.attrib.get('type'), defaults=dict())
            item.fromXml(node, 'fake')
            self.assertFalse(item.selectFirstChoice)

            node = et.fromstring('<input type="dropdown" token="foo">'
                                 '<selectFirstChoice>foobar</selectFirstChoice>'
                                 '</input>')
            item = createInput(node.attrib.get('type'), defaults=dict())
            item.fromXml(node, 'fake')
            self.assertFalse(item.selectFirstChoice)

            # first occurrence of <selectFirstChoice> takes precedence
            node = et.fromstring('<input type="dropdown" token="foo">'
                                 '<selectFirstChoice>foobar</selectFirstChoice>'
                                 '<selectFirstChoice>true</selectFirstChoice>'
                                 '</input>')
            item = createInput(node.attrib.get('type'), defaults=dict())
            item.fromXml(node, 'fake')
            self.assertFalse(item.selectFirstChoice)

            node = et.fromstring('<input type="dropdown" token="foo">'
                                 '<selectFirstChoice></selectFirstChoice>'
                                 '</input>')
            item = createInput(node.attrib.get('type'), defaults=dict())
            item.fromXml(node, 'fake')
            self.assertFalse(item.selectFirstChoice)

            node = et.fromstring('<input type="dropdown" token="foo">'
                                 '<selectFirstChoice />'
                                 '</input>')
            item = createInput(node.attrib.get('type'), defaults=dict())
            item.fromXml(node, 'fake')
            self.assertFalse(item.selectFirstChoice)

    loader = unittest.TestLoader()
    suites = [loader.loadTestsFromTestCase(test) for test in (MultiValueInputTests, CheckboxInputTests, SelectFirstChoiceTests)]
    unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites))
