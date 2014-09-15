#!/bin/sh


rm -R target
mkdir -p target/build/splunk-search-tools-app
cp -R bin target/build/splunk-search-tools-app/bin
cp -R default target/build/splunk-search-tools-app/default
cp -R metadata target/build/splunk-search-tools-app/metadata

rm -R target/build/splunk-search-tools-app/bin/splunk
rm -R target/build/splunk-search-tools-app/bin/examples
tar cvzf target/splunk-search-tools-app.tgz --directory=target/build/ splunk-search-tools-app



rm -R /Applications/Splunk/etc/apps/splunk-search-tools-app
cp -R target/build/splunk-search-tools-app /Applications/Splunk/etc/apps/
rm -R target/build/

