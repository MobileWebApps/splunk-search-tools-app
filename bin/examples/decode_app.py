#!/usr/bin/env python
#
# Copyright 2011-2014 Splunk, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"): you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import sys

from splunklib.searchcommands import \
    dispatch, StreamingCommand, Configuration, Option, validators
from base64 import b64decode, urlsafe_b64decode
from re import sub



@Configuration()
class DecodeCommand(StreamingCommand):
    """ Decodes a field and puts the value into a new '<fieldname>_decoded' field.

    ##Syntax

    .. code-block::
        countmatches fieldname=<field> pattern=<regular_expression> <field-list>

    ##Description


    """
    fieldname = Option(
        doc='''
        **Syntax:** **fieldname=***<fieldname>*
        **Description:** Field to be decoded''',
        require=True, validate=validators.Fieldname())

    autofix = Option(
        doc='''
        **Syntax:** **fixpadding=***<True|False>*
        **Description:** Fix Base64 padding issues''',
        require=False, validate=validators.Boolean(), default=False)

    type = Option(
        doc='''
        **Syntax:** **type=***<base64 | urlsafe_base64>*
        **Description:** Decoding type. Default = base64''',
        require=False, default='base64')

    suffix = Option(
        doc='''
        **Syntax:** **suffix=***< string >*
        **Description:** Suffix to be appended to the decoded field. Default = _decoded''',
        require=False, default='_decoded')

    def stream(self, records):

        self.logger.debug('decodeCommand: %s' % self)  # logs command line

        if type == 'urlsafe_base64':
            decodeMethod = urlsafe_b64decode
        else:
            decodeMethod = b64decode

        for record in records:

            for fieldname in self.fieldnames:

                record["TTTTTTT"] = record[fieldname]

                try:
                    decodeStr = record[fieldname]

                    if self.autofix:
                        # Fixes padding sign to the correct Base64 equals padding symbol
                        decodeStr = sub(r'[^0-9a-zA-Z+/]','=', record[fieldname])

                    record[fieldname] = decodeMethod(decodeStr)

                except Exception, e:
                    record[fieldname] = "[Error] Can't decode: " + e

            yield record


dispatch(DecodeCommand, sys.argv, sys.stdin, sys.stdout, __name__)