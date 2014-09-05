'''
Custom app-packaged CherryPy endpoint handler

This module enables Splunk apps to package their own splunkweb HTTP handlers
that can provide custom functionality.

This uses Python's import hooks to dynamically locate and import python modules
from apps.  This looks specifically for files that match the pattern:

    $SPLUNK_HOME/etc/apps/.../appserver/controllers/*.py

and contain a class that inherits from:

    splunk.appserver.mrsparkle.controllers.BaseController

The second part of this file is the actual CherryPy mount point that routes the
requests over to the registered app-packaged controllers.

See: http://www.python.org/dev/peps/pep-0302/
'''

import imp
import inspect
import logging
import os
import re
import sys
from subprocess import PIPE

import cherrypy
import splunk

from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib.util import get_apps_dir, Popen
import splunk.appserver.mrsparkle.controllers as controllers
import splunk.entity as en

logger = logging.getLogger('splunk.appserver.mrsparkle.controllers.custom')


# define the python package space in which to house custom controllers
# thay may be packaged with apps
VIRTUAL_PACKAGE_NAME = 'splunk.appserver.mrsparkle.custom_controllers'
VIRTUAL_PACKAGE_LENGTH = 4

# define the local filepath to the apps dir
ETC_PATH = get_apps_dir()

# define path segment within an apps dir
CONTROLLER_SUBPATH = os.path.join('appserver', 'controllers')


class ControllerMetaLoader(object):
    '''
    Unified import hook handler.  Implements base methods to support dynamic
    module importing via the meta hooks method.
    '''

    __qualified_apps = []


    @classmethod
    def crawl_apps(cls):
        '''
        Generates the list of apps that appear to have the correct directory
        structure for housing custom endpoints.
        '''

        cls.__qualified_apps = []        
        for path in os.listdir(ETC_PATH):
            eligible_dir = os.path.join(ETC_PATH, path, CONTROLLER_SUBPATH)
            if os.path.isdir(eligible_dir):
                cls.__qualified_apps.append(path)
        

    @classmethod
    def get_apps(self):
        '''
        Returns the list of eligible app names
        '''
        return ControllerMetaLoader.__qualified_apps


    @classmethod
    def get_registered_endpoints(cls, app):
        '''
        Returns a list of endpoints registered by app developer in web.conf
        '''

        listing = Popen(['btool', '--app=%s' % app, 'web', 'list'], stdout=PIPE, close_fds=True).communicate()[0]
        lines = listing.split('\n')
        rex = re.compile(r'\s*\[endpoint:([A-Za-z0-9_]+)')
        output = []
        for line in lines:
            match = rex.search(line)
            if match:
                output.append(match.group(1))
        return output


    def find_module(self, module_name, package_path=None):
        '''
        Required import hook implementation.

        Inspects the current request to see if it's an import for something
        inside of the module, as defined in VIRTUAL_PACKAGE_NAME.  If we
        can handle, then return self for the load phase; otherwise return
        null to let the next import hook try.
        '''

        # ignore anything outside of the main path
        if not module_name.startswith(VIRTUAL_PACKAGE_NAME):
            return
        
        # handle the traversal of the ancestral package names
        if module_name == VIRTUAL_PACKAGE_NAME:
            return self
        
        # check that the app looks like it might have a controller
        module_parts = module_name.split('.')
        if len(module_parts) > VIRTUAL_PACKAGE_LENGTH \
            and module_parts[VIRTUAL_PACKAGE_LENGTH] in self.get_apps():
            return self

        # nothing found; pass on to next locator
        return


    def load_module(self, full_name):
        '''
        Required import hook implementation.

        Returns a new module object if the import path is found; otherwise
        return null to throw ImportError.
        '''
        
        relative_name = full_name.replace(VIRTUAL_PACKAGE_NAME, '').strip('.')
        relative_parts = relative_name.split('.')
        namespace = relative_parts[0]

        # if at the app module, just treat as a package container
        if len(relative_parts) < 2:
            mod = sys.modules.setdefault(full_name, imp.new_module(full_name))
            mod.__file__ = '<virtual package: %s>' % (VIRTUAL_PACKAGE_NAME + '.' + '.'.join(relative_parts))
            mod.__loader__ = self
            mod.__path__ = []
            logger.debug('LOAD: returning wrapper package: %s' % mod.__file__)
            return mod

        # grab python code
        module_name = relative_parts[1]
        file_path = os.path.join(ETC_PATH, namespace, CONTROLLER_SUBPATH, module_name + '.py')
        logger.debug('LOAD: reading file: %s' % file_path)
        
        f = None
        code = None
        try:
            f = open(file_path, 'rU')
            code = ''.join(f.readlines())
        except Exception, e:
            logger.debug(e)
        finally:
            if f:
                f.close()

        if not code:
            return

        # create a module from the code
        mod = sys.modules.setdefault(full_name, imp.new_module(full_name))
        mod.__file__ = '<virtual module: %s>' % full_name
        mod.__loader__ = self
        exec code in mod.__dict__
        return mod



class CustomController(controllers.BaseController):
    '''
    CherryPy controller mount point
    '''

    def load_handlers(self):

        for app in ControllerMetaLoader.get_apps():
            
            # first add an app controller here
            setattr(self, app, controllers.BaseController())
            
            for endpoint in ControllerMetaLoader.get_registered_endpoints(app):
                
                # import the module
                try:
                    full_module = '.'.join([VIRTUAL_PACKAGE_NAME, app, endpoint])
                    __import__(full_module)
                    mod = sys.modules[full_module]
                except Exception, e:
                    logger.error('cannot load specified module %s in app %s: %s' % (endpoint, app, e))
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.exception(e)
                    continue
                
                # find the first BaseController sub-class in the module and
                # attach it
                for prop in mod.__dict__:
                    try:
                        if inspect.isclass(mod.__dict__[prop]) and \
                                issubclass(mod.__dict__[prop], controllers.BaseController):
                            setattr(getattr(self, app), endpoint, mod.__dict__[prop]())
                            logger.info('Registering custom app endpoint: %s/%s' % (app, endpoint))
                            break 
                    except Exception, e:
                        logger.exception(e)



# init meta loader and read in apps
sys.meta_path.append(ControllerMetaLoader())
ControllerMetaLoader.crawl_apps()

