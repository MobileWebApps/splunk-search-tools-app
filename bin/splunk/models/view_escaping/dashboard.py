import logging

logger = logging.getLogger('splunk.models.transview.dashboard')


class SimpleDashboard(object):

    matchTagName = 'dashboard'

    # define set of default attributes to assign to view
    standardAttributeMap = {
        'displayView': None,
        'isVisible': True,
        'isDashboard': True,
        'onunloadCancelJobs': True,
        'autoCancelInterval': 90,
        'refresh': -1,
        'stylesheet': None,
        'objectMode': 'SimpleDashboard'
    }

    # define attributes that are to be cast to boolean
    booleanAttributeKeys = ['isVisible', 'onunloadCancelJobs']

    # define attributes that are to be cast to integers
    integerAttributeKeys = ['refresh', 'autoCancelInterval']

    def __init__(self, viewName=None, digest=None, isStorm=False, sourceApp=None):
        self.sourceApp = sourceApp
        self.viewName = viewName
        self.digest = digest
        self.context = None
        self.searchTemplate = None
        self.label = None
        self.description = None
        self.isStorm = isStorm
        # set core view properties
        for k, v in self.standardAttributeMap.items():
            setattr(self, k, v)

        # init panel container
        self.rows = []
        self.rowGrouping = []
        self.searchContexts = []

        # instance members to track comment tags
        self.topLevelComments = []
        self.perRowComments = []  # will be a list of lists for comments by row

        # init form element container
        self.fieldset = []
        self.submitButton = False

        self.autoRun = True

        self.onUnloadCancelJobs = True

    def all_elements(self):
        for row in self.rows:
            for panel in row.panels:
                for el in panel.panelElements:
                    yield el

    def has_fields(self):
        return self.fieldset or getattr(self, 'submitButton', False) or len([f for f in self.all_fields()])

    def all_fields(self):
        for field in self.fieldset:
            yield field
        for row in self.rows:
            for panel in row.panels:
                for input in panel.fieldset:
                    yield input

    def getFieldJSON(self):
        fields = []
        for field in self.fieldset:
            fields.append(field.id)
        return '[' + ','.join(fields) + ']'

    def getSearchesJSON(self):
        searches = []
        for search in self.all_elements():
            if getattr(search, 'context', None):
                searches.append(search.context)
        return '[' + ','.join(searches) + ']'

    def normalizedSearchCommand(self):
        stripped = self.searchTemplate.lstrip()
        return self.searchTemplate if (stripped.startswith('search') or stripped.startswith('|')) else 'search ' + self.searchTemplate

    def hasGlobalTRP(self):
        for input in self.all_fields():
            if input.matchTagName == "time" and input.token is None:
                return True
        return False


if __name__ == '__main__':
    import unittest
    from row import Row
    from panel import Panel
    from panelElement import BasePanel
    from forminput import BaseInput

    class SimpleDashboardTests(unittest.TestCase):
        def testAllElementsGenerator(self):
            dashboard = SimpleDashboard()
            dashboard.rows.append(Row())
            dashboard.rows.append(Row())
            dashboard.rows[0].panels.append(Panel())
            dashboard.rows[0].panels.append(Panel())
            dashboard.rows[1].panels.append(Panel())
            dashboard.rows[0].panels[0].panelElements.append(1)
            dashboard.rows[0].panels[0].panelElements.append(2)
            dashboard.rows[0].panels[1].panelElements.append(3)
            dashboard.rows[1].panels[0].panelElements.append(4)

            result = []
            for el in dashboard.all_elements():
                result.append(el)

            self.assertEquals(4, len(result))
            self.assertTrue(1 in result)
            self.assertTrue(2 in result)
            self.assertTrue(3 in result)
            self.assertTrue(4 in result)

        def testFieldsJSON(self):
            dashboard = SimpleDashboard()
            dashboard.rows.append(Row())
            self.assertEquals('[]', dashboard.getFieldJSON())

            input = BaseInput()
            input.id = 'input1'
            dashboard.fieldset.append(input)
            self.assertEquals('[input1]', dashboard.getFieldJSON())

            input = BaseInput()
            input.id = 'input2'
            dashboard.fieldset.append(input)
            self.assertEquals('[input1,input2]', dashboard.getFieldJSON())

        def testSearchesJSON(self):
            dashboard = SimpleDashboard()
            self.assertEquals('[]', dashboard.getSearchesJSON())
            dashboard.rows.append(Row())
            dashboard.rows[0].panels.append(Panel())
            el = BasePanel()
            dashboard.rows[0].panels[0].panelElements.append(el)
            el.searchCommand = "search index=_internal"
            el.searchEarliestTime = '-24h'
            el.context = 'search1'
            self.assertEquals('[search1]', dashboard.getSearchesJSON())
            el = BasePanel()
            dashboard.rows[0].panels[0].panelElements.append(el)
            el.searchCommand = "search index=_internal"
            el.searchEarliestTime = '-24h'
            el.context = 'search2'
            self.assertEquals('[search1,search2]', dashboard.getSearchesJSON())

    loader = unittest.TestLoader()
    suites = []
    suites.append(loader.loadTestsFromTestCase(SimpleDashboardTests))
    unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites))
