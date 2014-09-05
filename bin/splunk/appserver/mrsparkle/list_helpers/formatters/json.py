import json
from splunk.appserver.mrsparkle.list_helpers.formatters import BaseFormatter

class JsonFormatter(BaseFormatter):
    
    formats = 'json'
    
    def format(self):
        try:
            return json.dumps(self.response)
        except Exception, e:
            return json.dumps({'error': e.message})
        
