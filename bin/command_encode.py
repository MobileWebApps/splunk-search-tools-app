import logging
import splunklib.searchcommands.logging as splunkLibLogging
from base64 import b64encode, urlsafe_b64encode
import hashlib
from re import sub

import splunk.Intersplunk


'''
 You can then search for errors created by your custom search script by searching like so:

        index=_internal source=*python.log*

'''
#_logging_configuration = splunkLibLogging.configure("EncodeCommand")
logger = logging.getLogger("EncodeCommand")



def process_results():
    # Handle key/value and args passed in to my script
    search_fields, search_parameters = splunk.Intersplunk.getKeywordsAndOptions()

    # Fetch results being passed to this search command
    (results, dummyresults, settings) = splunk.Intersplunk.getOrganizedResults()

    logger.debug("Args:  %r, key/value settings:  %r", search_fields, search_parameters)
    logger.debug("Settings passed:  %r", settings)
    logger.debug("Custom search script processing %d results.", len(results))

    decoded_results = encode_results(results, search_fields, search_parameters)

    #  Return modified results back to splunk (for the next search command to process)
    splunk.Intersplunk.outputResults(decoded_results)


def hashlib_decode(algo):

    def decode(string):
        hash_object = hashlib.new(algo)
        hash_object.update(string)
        return hash_object.hexdigest()
    return decode


def encode_results(results, search_fields, search_parameters):

    type = search_parameters.get('type', 'base64')
    suffix = search_parameters.get('suffix', '_'+type)

    if type == 'base64':
        encodeMethod = b64encode
    elif type == 'urlsafe_base64':
        encodeMethod = urlsafe_b64encode
    else:
        encodeMethod = hashlib_decode(type)

    for result in results:

        for fieldname in search_fields:

            if fieldname not in result:
                continue

            try:
                encodeStr = result[fieldname]
                result[fieldname+suffix] = encodeMethod(encodeStr)

            except Exception, e:
                result[fieldname+suffix] = "[Error] " + type + " encode: " + str(e)

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
