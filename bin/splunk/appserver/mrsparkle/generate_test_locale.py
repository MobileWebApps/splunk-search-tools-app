# 1. run this in $SPLUNK_HOME/lib/python2.7/site-packages/splunk/appserver/mrsparkle/locale
# 2. pass in args of: messages.pot <locale>
# 3. I test using th-TH 
# 4. splunk restartss

import sys, os, subprocess, os.path, re

print 'Arguments: %s' % sys.argv

if len(sys.argv) < 3:
    print 'ERROR: must specify input file and output directory name'

pot_filename = sys.argv[1]
output_dir = sys.argv[2]

print 'pot_filename: %s' % pot_filename
print 'output_dir: %s' % output_dir

#
# build locale directory
#
os.mkdir(output_dir)
lc_messages_dir = os.path.join(output_dir, 'LC_MESSAGES')
os.mkdir(lc_messages_dir)

#
# build po file
#
po_filename = 'messages.po'

pot_file = open(pot_filename, 'r')
po_file = open(os.path.join(lc_messages_dir, po_filename), 'a')

test = 0
msglines = []
matcher = re.compile('\"(\\\"|[^"])*\"')
for line in pot_file:
    if "msgid" in line:
        msglines = []

    if "msgstr" in line:
        output_msglines = []
        for msgline in msglines:
            # translate everything but backslahed characters and string formatting i.e. %s %(name)s
            splits = re.split('(\\\\.|%s|%\([^\)]*\)s)', msgline)
            outputsplits = []
            for split in splits:
                outputsplit = split
                if split.startswith('%') == False:
                    if split.startswith('\\') == False:
                        outputsplit = re.sub('\w', 'X', split)
                outputsplits.append(outputsplit)
             
            output_msglines.append("".join(outputsplits))

        if len(output_msglines) > 0:
            po_file.write(line.replace('""', '%s' % output_msglines[0]))       
        if len(output_msglines) > 1:
            for i in range(1, len(output_msglines)):
                po_file.write('%s\n' % output_msglines[i])
    else: 
        match = matcher.search(line)
        if match:
            msglines.append('%s' % match.group(0))

        po_file.write(line)

pot_file.close()
po_file.close()   

#
# build mo file
#
os.chdir(lc_messages_dir)
subprocess.call([os.path.join(os.environ['SPLUNK_SOURCE'],*'contrib/Python-2.7.5/Tools/i18n/msgfmt.py'.split('/')), po_filename])

