splunk-search-tools-app
=============================================

This app extends splunk search with extra commands.


 Command      | Type       | Description
:------------ |:-----------|:----------------------------------------------------
 encode       | Generating | Encodes search fields on a variety of algos <[base64]|urlsafe_base64|md5|dsa|any hashlib algo>
 decode       | Reporting  | Decodes search fields outputting results to <field>+suffix.

The app is tested on 6. Here is its manifest:

**References**  
[1] [splunk-sdk-python](http://dev.splunk.com/view/python-sdk/SP-CAAAEBB) 
[2] [app.conf](http://docs.splunk.com/Documentation/Splunk/latest/Admin/Appconf app.conf)  
[3] [commands.conf](http://docs.splunk.com/Documentation/Splunk/latest/Admin/Commandsconf)  
[4] [Python Logging HOWTO](http://docs.python.org/2/howto/logging.html)  
[5] [ConfigParser—Configuration file parser](http://docs.python.org/2/library/configparser.html)
[6] [searchbnf.conf](http://docs.splunk.com/Documentation/Splunk/latest/admin/Searchbnfconf)
[7] [Set permissions in the file system](http://goo.gl/1oDT7r)

## Installation

+ Package the app by running the `package.sh`.

+ Install the app by expanding the resulting `target/splunk-search-tools-app.tgz` into `$SPLUNK_HOME/etc/apps/`.

+ (Re)start Splunk so that the app is recognized.

+ you can also use the Splunk web interface to install `splunk-search-tools-app.tgz`  


## License

This software is licensed under the Apache License 2.0. Details can be found in
the file LICENSE.
