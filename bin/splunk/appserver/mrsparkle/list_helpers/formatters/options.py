import logging
import cherrypy
import cgi
from splunk.appserver.mrsparkle.list_helpers.formatters import BaseFormatter

logger = logging.getLogger('splunk.appserver.mrsparkle.list_helpers.formatters.options')

class OptionsFormatter(BaseFormatter):
    
    formats = 'option'
    
    def format(self):
        response = []
        text = self.params.get('text')

        if text == None:
            raise cherrypy.HTTPError(status=400, message="Option formatter requires a text parameter be defined. Hint: try adding ?text=foo to your URI.")

        value = self.params.get('value')
        selected = self.params.get('selected')

        for elem in self.response:
            if elem.has_key(text):
                elem_html = ['<option']
                if value and elem.has_key(value):
                    elem_html.append(' value="%s"' % cgi.escape(unicode(elem[value])))
                    if not selected == None and elem[value] == selected:
                        elem_html.append(' selected="selected"')
                else:
                    if not selected == None and elem[text] == selected:
                        elem_html.append(' selected="selected"')
                    
                elem_html.append('>%s</option>' % cgi.escape(unicode(elem[text])))
                response.append(''.join(elem_html))
            else:
                logger.info("Can't find the field %(field)s in this response object %(resp)s while trying to convert it to an options list." % {'field': text, 'resp': elem})

        return '\n'.join(response)
