from panelElement import *
import logging
import lxml.etree as et

logger = logging.getLogger('splunk.models.view_escaping.drilldown')

EXPLICT_CONDITION = True
IMPLICIT_CONDITION = False


def parseDrilldownAction(node, defaultLinkTarget=None):
    if node.tag == 'set':
        name = node.attrib.get('token', '').strip()
        if not name:
            logger.warn('Ignoring token action without token name %s', et.tostring(node))
            return
        if node.text is None:
            logger.warn('Missing text template for token action node %s', et.tostring(node))
            return
        return SetToken(
            name=name,
            template=node.text.strip(),
            prefix=node.attrib.get('prefix', None),
            suffix=node.attrib.get('suffix', None)
        )

    elif node.tag == 'unset':
        name = node.attrib.get('token', '').strip()
        if not name:
            logger.warn('Ignoring token action without token name %s', et.tostring(node))
            return
        return UnsetToken(name=name)

    elif node.tag == 'link':
        if node.text is None:
            logger.warn('Missing text template for link action node %s', et.tostring(node))
            return
        return Link(
            link=node.text.strip().replace("\n", " "),
            target=node.attrib.get(
                'target') if 'target' in node.attrib else defaultLinkTarget
        )
    else:
        logger.warn('Ignoring unrecognized drilldown action %s', et.tostring(node))


def checkField(field, fieldMap, node):
    if field in fieldMap:
        logger.warn('Duplicate condition for field="%s" found for drilldown. Overriding previous conditions '
                    'with %s. (line %d)', field, et.tostring(node).strip().replace('\n', ' '), node.sourceline)
    else:
        fieldMap[field] = True


def parseDrilldown(drilldownNode):
    defaultTarget = drilldownNode.get('target') if (drilldownNode is not None) else None
    results = list()
    fieldMap = dict()
    conditionsType = None
    implicitCondition = None

    if drilldownNode is not None:
        for drilldownNode in [node for node in drilldownNode if et.iselement(node) and type(node.tag) is str]:
            nodeName = drilldownNode.tag.lower()
            if nodeName == 'link':
                if conditionsType is None:
                    conditionsType = IMPLICIT_CONDITION
                elif conditionsType is EXPLICT_CONDITION:
                    raise AttributeError('Cannot mix <%s> with explicit <condition>s (line %d)' %
                                         (nodeName, drilldownNode.sourceline))
                field = drilldownNode.attrib.get('field')
                series = drilldownNode.attrib.get('series')
                if not field and series:
                    field = series
                if not field:
                    field = '*'
                if drilldownNode.text and len(drilldownNode.text) == 0:
                    continue
                action = parseDrilldownAction(drilldownNode, defaultLinkTarget=defaultTarget)
                if action is not None:
                    checkField(field, fieldMap, drilldownNode)
                    if field == '*':
                        if implicitCondition is None:
                            implicitCondition = Condition(field='*')
                            results.append(implicitCondition)
                        implicitCondition.add(action)
                    else:
                        results.append(Condition(field=field, action=action))
            elif nodeName in ('set', 'unset'):
                if conditionsType is None:
                    conditionsType = IMPLICIT_CONDITION
                elif conditionsType is EXPLICT_CONDITION:
                    raise AttributeError('Cannot mix <%s> with explicit <condition>s' % nodeName)
                if 'field' in drilldownNode.attrib:
                    logger.warn('Ignoring field attribute for top-level <%s> action, assuming field="*" (line %d)',
                                nodeName, drilldownNode.sourceline)
                action = parseDrilldownAction(drilldownNode, defaultLinkTarget=defaultTarget)
                if action is not None:
                    checkField('*', fieldMap, drilldownNode)
                    if implicitCondition is None:
                        implicitCondition = Condition(field='*')
                        results.append(implicitCondition)
                    implicitCondition.add(action)
            elif nodeName == 'condition':
                if conditionsType is None:
                    conditionsType = EXPLICT_CONDITION
                elif conditionsType is IMPLICIT_CONDITION:
                    raise AttributeError('Cannot mix <%s> with implicit conditions (line %d)' %
                                         (nodeName, drilldownNode.sourceline))
                field = drilldownNode.attrib.get('field', '*')
                checkField(field, fieldMap, drilldownNode)
                condition = Condition(field=field)
                for node in [node for node in drilldownNode if et.iselement(node) and type(node.tag) is str]:
                    action = parseDrilldownAction(node, defaultLinkTarget=defaultTarget)
                    if action is not None:
                        condition.add(action)

                results.append(condition)
            else:
                logger.warn('Ignoring unrecognized drilldown node "%s" (line %d)', nodeName, drilldownNode.sourceline)

    return results


class Condition:
    def __init__(self, field, action=None):
        self.field = field
        self.wildcard = field == '*'
        self.actions = []
        if action is not None:
            self.add(action)

    def add(self, item):
        self.actions.append(item)


class DrilldownAction:
    def __init__(self, drilldownType):
        self.type = drilldownType


class Link(DrilldownAction):
    def __init__(self, link, target):
        DrilldownAction.__init__(self, 'link')
        self.link = link
        self.target = target


class SetToken(DrilldownAction):
    def __init__(self, name, template, prefix=None, suffix=None):
        DrilldownAction.__init__(self, 'settoken')
        self.name = name
        self.template = template
        self.prefix = prefix
        self.suffix = suffix


class UnsetToken(DrilldownAction):
    def __init__(self, name):
        DrilldownAction.__init__(self, 'unsettoken')
        self.name = name


if __name__ == '__main__':
    import unittest

    class DrilldownParserTests(unittest.TestCase):
        def testParseEmptyDrilldownNode(self):
            result = parseDrilldown(et.fromstring('''<drilldown></drilldown>'''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 0)
            result = parseDrilldown(et.fromstring('''<drilldown />'''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 0)
            self.assertTrue(isinstance(result, list))
            result = parseDrilldown(et.fromstring('''<foo></foo>'''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 0)
            self.assertTrue(isinstance(result, list))
            result = parseDrilldown(None)
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 0)
            self.assertTrue(isinstance(result, list))

        def testParseEmptyCondition(self):
            result = parseDrilldown(et.fromstring('''
                    <drilldown>
                        <condition field="foo"></condition>
                    </drilldown>
                '''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 1)
            cond = result[0]
            self.assertEqual(cond.field, 'foo')
            self.assertEqual(len(cond.actions), 0)

        def testParseSimpleLinkNodes(self):
            result = parseDrilldown(et.fromstring('''
            
                <drilldown>
                    <link field="foo">/foo/bar</link>
                    <link field="bar" target="_blank">/foo/bar</link>
                </drilldown>
            '''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 2)
            cond = result[0]
            self.assertEqual(cond.field, 'foo')
            self.assertEqual(len(cond.actions), 1)
            self.assertTrue(isinstance(cond.actions[0], Link))
            self.assertEqual(cond.actions[0].link, '/foo/bar')
            self.assertEqual(cond.actions[0].target, None)
            cond = result[1]
            self.assertEqual(cond.field, 'bar')
            self.assertEqual(len(cond.actions), 1)
            self.assertEqual(cond.actions[0].type, 'link')
            self.assertEqual(cond.actions[0].link, '/foo/bar')
            self.assertEqual(cond.actions[0].target, '_blank')

        def testParseLinkInCondition(self):
            result = parseDrilldown(et.fromstring('''
            
                <drilldown>
                    <condition field="foo">
                        <link>/foo/bar</link>
                    </condition>
                    <condition field="bar">
                        <link target="_blank">/foo/bar</link>
                    </condition>
                </drilldown>
            '''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 2)
            cond = result[0]
            self.assertEqual(cond.field, 'foo')
            self.assertEqual(len(cond.actions), 1)
            self.assertTrue(isinstance(cond.actions[0], Link))
            self.assertEqual(cond.actions[0].link, '/foo/bar')
            self.assertEqual(cond.actions[0].target, None)
            cond = result[1]
            self.assertEqual(cond.field, 'bar')
            self.assertEqual(len(cond.actions), 1)
            self.assertEqual(cond.actions[0].type, 'link')
            self.assertEqual(cond.actions[0].link, '/foo/bar')
            self.assertEqual(cond.actions[0].target, '_blank')

        def testParseTokenInCondition(self):
            result = parseDrilldown(et.fromstring('''
                <drilldown>
                    <condition field="*">
                        <set token="foo">$click.value$</set>
                        <set token="foobar">
                            $click.value$
                        </set>
                        <unset token="bar" />
                    </condition>
                </drilldown>
            '''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 1)
            cond = result[0]
            self.assertEqual(len(cond.actions), 3)
            action = cond.actions[0]
            self.assertEqual(action.type, 'settoken')
            self.assertEqual(action.name, 'foo')
            self.assertEqual(action.template, '$click.value$')
            action = cond.actions[1]
            self.assertEqual(action.type, 'settoken')
            self.assertEqual(action.name, 'foobar')
            self.assertEqual(action.template, '$click.value$')
            action = cond.actions[2]
            self.assertEqual(action.type, 'unsettoken')
            self.assertEqual(action.name, 'bar')

        def testParseImplicitLinkAction(self):
            result = parseDrilldown(et.fromstring('''
                <drilldown>
                    <link>/foo/bar</link>
                </drilldown>
            '''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 1)
            cond = result[0]
            self.assertEqual(cond.field, '*')
            self.assertEqual(len(cond.actions), 1)
            action = cond.actions[0]
            self.assertEqual(action.type, 'link')

        def testParseImplicitSetTokenAction(self):
            result = parseDrilldown(et.fromstring('''
                <drilldown>
                    <set token="foo">$click.value$</set>
                </drilldown>
            '''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 1)
            cond = result[0]
            self.assertEqual(cond.field, '*')
            self.assertEqual(len(cond.actions), 1)
            action = cond.actions[0]
            self.assertEqual(action.type, 'settoken')
            self.assertEqual(action.name, 'foo')
            self.assertEqual(action.template, '$click.value$')

        def testParseImplicitSetTokenActions(self):
            result = parseDrilldown(et.fromstring('''
                <drilldown>
                    <set token="foo">$click.value$</set>
                    <set token="bar">$click.value2$</set>
                    <unset token="foobar" />
                </drilldown>
            '''))
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 1)
            cond = result[0]
            self.assertEqual(cond.field, '*')
            self.assertEqual(len(cond.actions), 3)
            action = cond.actions[0]
            self.assertEqual(action.type, 'settoken')
            self.assertEqual(action.name, 'foo')
            self.assertEqual(action.template, '$click.value$')
            action = cond.actions[1]
            self.assertEqual(action.type, 'settoken')
            self.assertEqual(action.name, 'bar')
            self.assertEqual(action.template, '$click.value2$')
            action = cond.actions[2]
            self.assertEqual(action.type, 'unsettoken')
            self.assertEqual(action.name, 'foobar')

        def testParserDoesNotFailWithComments(self):
            result = parseDrilldown(et.fromstring('''
                <drilldown>
                    <!-- this is a comment -->
                    <condition field="foo">
                        <set token="blah">$click.value$</set>
                        <!-- another comment -->
                        <set token="buh"><!-- some comment--></set>
                        <link><!-- comment comment --></link>
                    </condition>
                </drilldown>
            '''))
            self.assertIsNotNone(result)

        def testParsePrefixAndSuffixForSet(self):
            result = parseDrilldown(et.fromstring('''
                <drilldown>
                    <set token="foo" prefix="sourcetype=&quot;" suffix="&quot;">$click.value$</set>
                </drilldown>
            '''))
            action = result[0].actions[0]
            self.assertEquals(action.name, 'foo')
            self.assertEquals(action.prefix, 'sourcetype="')
            self.assertEquals(action.suffix, '"')

            result = parseDrilldown(et.fromstring('''
                <drilldown>
                    <set token="foo">$click.value|s$</set>
                </drilldown>
            '''))
            action = result[0].actions[0]
            self.assertEquals(action.name, 'foo')
            self.assertIsNone(action.prefix)
            self.assertIsNone(action.suffix)

        def testMixedConditionsRaisesError(self):

            with self.assertRaises(AttributeError):
                parseDrilldown(et.fromstring('''
                    <drilldown>
                        <set token="foo">...</set>
                        <condition field="foobar">
                            <set token="bar">...</set>
                        </condition>
                    </drilldown>
                '''))

            with self.assertRaises(AttributeError):
                parseDrilldown(et.fromstring('''
                    <drilldown>
                        <condition field="foobar">
                            <set token="bar">...</set>
                        </condition>
                        <set token="foo">...</set>
                    </drilldown>
                '''))

            with self.assertRaises(AttributeError):
                parseDrilldown(et.fromstring('''
                    <drilldown>
                        <set token="foo">...</set>
                        <condition field="foobar">
                            <set token="bar">...</set>
                        </condition>
                        <unset token="foo" />
                    </drilldown>
                '''))

    logger.setLevel(logging.ERROR)
    loader = unittest.TestLoader()
    suite = [loader.loadTestsFromTestCase(case) for case in (DrilldownParserTests,)]
    unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suite))