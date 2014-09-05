"""
CherryPy based appserver
"""

# unit tests etc require that the mrsparkle directory be on the path
import os, sys
localDir = os.path.abspath(os.path.dirname(__file__))
if localDir not in sys.path:
    sys.path.insert(0, localDir)


# import commonly used stuff
from lib.decorators import *
from lib.routes import route
from controllers import BaseController


# define common MIME types
MIME_HTML = 'text/html; charset=utf-8'
MIME_JSON = 'application/json; charset=utf-8'
MIME_TEXT = 'text/plain; charset=utf-8'
MIME_XML = 'text/xml; charset=utf-8'
MIME_CSV = 'text/csv; charset=utf-8'
MIME_JAVASCRIPT = 'application/javascript'

# Define system namespace for use with non app-scoped assets like modules.
# Not to be confused with the default namespace, as set in splunk/__init__.py
SYSTEM_NAMESPACE = 'system'

