import os        
import splunk.entity as entity

def is_available(sessionKey):
    return is_pdfgen_available() or is_deprecated_service_available(sessionKey)

def is_pdfgen_available():
    # if we are not on x86, NODE_PATH will not exist,
    # and therefore, we won't be able to run integrated PDF
    nodeAvailable = "NODE_PATH" in os.environ
    if not nodeAvailable:
        return False
    return True

def is_deprecated_service_available(sessionKey):
    import splunk   
    import splunk.util
    import splunk.clilib.cli_common as comm
 
    ALERT_ACTIONS_ENTITY = '/configs/conf-alert_actions'
    
    try:
        settings = entity.getEntity(ALERT_ACTIONS_ENTITY, 'email', sessionKey=sessionKey)
        serverURL = settings.get('reportServerURL') or ''
        if serverURL.strip() == '':
            # if reportServerURL is blank then this system should actually have the app installed; check for that.
            # will raise a ResourceNotFound exception if not installed
            if comm.isWindows:
                # will raise a ResourceNotFound exception if our PDF driver is not installed
                entity.getEntity('/pdfserver', 'renderpdf', sessionKey=sessionKey)
            else:
                entity.getEntity('/apps/local', 'pdfserver', sessionKey=sessionKey)

        # next check that it's actually turned on in email settings;
        # on Windows, ther server is always enabled
        status = 'enabled' if comm.isWindows or splunk.util.normalizeBoolean(settings.get('reportServerEnabled')) else 'disabled'
    except splunk.ResourceNotFound:
        status = 'notinstalled'
    except splunk.AuthorizationFailed:
        status = 'denied'
    except splunk.LicenseRestriction:
        status = 'denied'

    return status is 'enabled'

def which_pdf_service(sessionKey, viewId=None, owner=None, namespace=None):
    pdfService = "none"
    
    if is_pdfgen_available():
        if viewId is None or (len(viewId) == 0):
            pdfService = "pdfgen"
        else:
            import lxml.etree as et

            # this is either a simple dashboard, simple form, or advanced XML view
            # get the entity of the view and then check the root node
            entityId = entity.buildEndpoint('data/ui/views', viewId, namespace=namespace, owner=owner)
            viewEntity = entity.getEntity('data/ui/views', None, sessionKey=sessionKey, uri=entityId)
            data = viewEntity['eai:data']
            if data:
                root = et.fromstring(unicode(data).encode('utf-8'))
                if root.tag == "dashboard":
                    pdfService = "pdfgen"
                else:
                    pdfService = "deprecated"
    else:
        pdfService = "deprecated"

    if pdfService is "deprecated" and not is_deprecated_service_available(sessionKey):
        pdfService = "none" 

    return pdfService
