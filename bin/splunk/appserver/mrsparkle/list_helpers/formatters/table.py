import logging
import cgi
from splunk.appserver.mrsparkle.list_helpers.formatters import BaseFormatter

logger = logging.getLogger('splunk.appserver.mrsparkle.list_helpers.formatters.table')

class TableFormatter(BaseFormatter):
    
    formats = 'table'
    
    def getFieldList(self):
        fields = self.params.get('field_list', False)
        if fields:
            return fields.split(',')
        return False
    
    def format(self):
        response = ['<table>']
        field_list = self.getFieldList()
        
        for elem in self.response:
            tr = ['<tr>']
            if field_list:
                for field in field_list:
                    if elem.has_key(field):
                        tr.append('<td class="%s">%s</td>' % (cgi.escape(unicode(field)), cgi.escape(unicode(elem[field]))))
                    else:
                        logger.warn('Cannot find field "%s" in the list data provided.' % field)
            else:
                for k,v in elem.iteritems():
                    tr.append('<td class="%s">%s</td>' % (cgi.escape(unicode(k)), cgi.escape(unicode(v))))
            tr.append('</tr>')
            response.append(''.join(tr))

        response.append('</table>')
        return '\n'.join(response)
