# coding=UTF-8
import cherrypy
from splunk.appserver.mrsparkle import *
from splunk.models.message import Message
import urllib

logger = logging.getLogger('splunk.appserver.controllers.wall')

class WallController(BaseController):
    @route('/:app/:action=new')
    @expose_page(must_login=True, methods='GET')
    def new(self, app, action, **params):
        owner = splunk.auth.getCurrentUser()['name']
        try:
            message = Message(app, owner, '', **params)
        except splunk.AuthorizationFailed:
            error = _("We're sorry you do not have permissions to use Wall.")
            return self.render_template('wall/error.html', dict(app=app, error=error))
        except Exception:
            error = _("We're sorry Wall is unavailable.")
            return self.render_template('wall/error.html', dict(app=app, error=error))
        else:
            return self.render_template('wall/new.html', dict(app=app, message=message))

    @route('/:app/:action=create')
    @expose_page(must_login=True, methods='POST')
    def create(self, app, action, **params):
        owner = splunk.auth.getCurrentUser()['name']
        message = Message(app, owner, **params)
        if message.value is None or len(message.value)==0:
            message.errors = [_('Please enter a value for your post')]
        else:
            url = "/app/search/flashtimeline?%s" % urllib.urlencode({"q": "search index=_* %s" % owner})
            label = "@%s" % owner
            wikified = "[[%s|%s]] %s" % (url, label, message.value)
            message.value = wikified
        if not message.errors and message.passive_save():
            raise cherrypy.HTTPRedirect(self.make_url(['wall', app, 'success']), 303)
        return self.render_template('wall/new.html', dict(app=app, message=message))

    @route('/:app/:action=success')
    @expose_page(must_login=True, methods='GET')
    def success(self, app, action, **params):
        messages = [message.entity[message.name] for message in Message.all()]
        message_value = None
        if messages>0:
            message_value = messages[0]
        return self.render_template('wall/success.html', dict(app=app, message_value=message_value))
