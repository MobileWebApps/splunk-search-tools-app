import logging
import splunklib.searchcommands.logging as splunkLibLogging
from base64 import b64decode, urlsafe_b64decode
from re import sub

import splunk.Intersplunk


'''
 You can then search for errors created by your custom search script by searching like so:

        index=_internal source=*python.log*

'''
#_logging_configuration = splunkLibLogging.configure("DecodeCommand")
logger = logging.getLogger("DecodeCommand")
#logger.setLevel(logging.DEBUG)



def process_results():
    # Handle key/value and args passed in to my script
    search_fields, search_parameters = splunk.Intersplunk.getKeywordsAndOptions()

    # Fetch results being passed to this search command
    (results, dummyresults, settings) = splunk.Intersplunk.getOrganizedResults()

    logger.debug("Args:  %r, key/value settings:  %r", search_fields, search_parameters)
    logger.debug("Settings passed:  %r", settings)
    logger.debug("Custom search script processing %d results.", len(results))

    decoded_results = decode_results(results, search_fields, search_parameters)

    #  Return modified results back to splunk (for the next search command to process)
    splunk.Intersplunk.outputResults(decoded_results)




def decode_results(results, search_fields, search_parameters):

    type = search_parameters.get('type', 'base64')
    autofix = search_parameters.get('autofix', False)
    suffix = search_parameters.get('suffix', '_decoded')

    if type == 'urlsafe_base64':
        decodeMethod = urlsafe_b64decode
    else:
        decodeMethod = b64decode

    for result in results:

        logger.debug("Results:  %r", result)
        logger.debug("search_fields:  %r", search_fields)

        for fieldname in search_fields:

            if fieldname not in result:
                continue

            try:
                decodeStr = result[fieldname]

                if autofix:
                    # Fixes padding sign to the correct Base64 equals padding symbol
                    decodeStr = sub(r'[^0-9a-zA-Z+/]','=', decodeStr)

                result[fieldname+suffix] = decodeMethod(decodeStr)

            except Exception, e:
                result[fieldname+suffix] = "[Error] " + type + " decode: " + str(e)

    return results



###########################

try:
    process_results()
except Exception, e:
    # Catch any exception, log it and also return a simplified version back to splunk (should be displayed in red at the top of the page)
    import traceback
    stack =  traceback.format_exc()
    results = splunk.Intersplunk.generateErrorResults("Error : Traceback: " + str(stack))
    raise e
