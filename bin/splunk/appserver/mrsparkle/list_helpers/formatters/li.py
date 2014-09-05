import logging
import cgi
from splunk.appserver.mrsparkle.list_helpers.formatters import BaseFormatter

logger = logging.getLogger('splunk.appserver.mrsparkle.list_helpers.formatters.li')

class LiFormatter(BaseFormatter):
    
    formats = 'li'
    
    def getFieldList(self):
        fields = self.params.get('field_list', False)
        if fields:
            return fields.split(',')
        return False
    
    def format(self):
        response = []
        field_list = self.getFieldList()
        
        for elem in self.response:
            li = ['<li>']
            if field_list:
                for field in field_list:
                    if elem.has_key(field):
                        li.append('<span class="%s">%s</span> ' % (cgi.escape(unicode(field)), cgi.escape(unicode(elem[field]))))
                    else:
                        logger.warn('Cannot find field "%(field)s" in the response element %(elem)s.' % {'field': field, 'elem': elem})
            else:
                for k,v in elem.iteritems():
                    li.append('<span class="%s">%s</span> ' % (cgi.escape(unicode(k)), cgi.escape(unicode(v))))
            li.append('</li>')
            response.append(''.join(li))
        return '\n'.join(response)
