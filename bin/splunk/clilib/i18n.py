#
# Extracts text to be translated from python, javascript and mako templates
# and compiles it into a .pot file


import sys, os.path
from babel.messages import frontend
import splunk.clilib.cli_common as comm


def i18n_extract(args, fromCLI):
    splunk_home = comm.splunk_home
    params_req = ('app',)
    params_opt = ()
    comm.validateArgs(params_req, params_opt, args)

    app_path = os.path.join(splunk_home, 'etc', 'apps', args['app'])
    app_locale_path = os.path.join(app_path, 'locale')
    if not os.path.exists(app_locale_path):
        os.makedirs(app_locale_path)

    messages_pot = os.path.join(app_locale_path, 'messages.pot')

    babel_cfg = os.path.join(app_locale_path, 'babel.cfg')
    if not os.path.exists(babel_cfg):
        from splunk.appserver.mrsparkle.lib import i18n
        mrsparkle = os.path.dirname(os.path.dirname(i18n.__file__))
        babel_cfg = os.path.join(mrsparkle, 'locale', 'babel.cfg')
    
    args = [ 
        'extract', 
        '-F',  babel_cfg,
        '-o', messages_pot,
        '-c', 'TRANS:',
        app_path
        ]

    sys.argv[1:] = args

    frontend.main()

