#!/usr/bin/env python
"""Apply some viscid-specific matplotlib styling

This module provides some extra style sheets as well as a layer to
set viscid-specific rc parameters and activate specific style sheets
from your `viscidrc` file.

Attributes:
    use_styles (sequence): a list of style sheet names to activate
    rc_params (dict): dictionary of parameters that get directly
        injected into matplotlib.rcParams
    rc (dict): specify rc parameters through matplotlib.rc(...). Keys
        are groups and the values should be dictionaries that will be
        unpacked into the rc function call.

Style Sheets:
    The following style sheets are available to matplotlib. Style
    sheets require matplotlib version >= 1.5.0

    - **viscid-default**: use afmhot
    - **viscid-steve**: use Steve's label formatter for colorbars

Rc Parameters:
    Here are some viscid-specific options that can be put into the
    matplotlib rcParams

    - **viscid.cbarfmt**: Formatter for colorbars
    - **viscid.majorfmt**: Major tick formatter
    - **viscid.minorfmt**: Minor tick formatter
    - **viscid.majorloc**: Major tick locator
    - **viscid.minorloc**: Minor tick locator
    - **image.cmap**: Default colormap
    - **viscid.symmetric_cmap**: Default colormap for plots with
       symmetric limits
"""
# matplotlib's style sheets can be browsed at:
# https://github.com/matplotlib/matplotlib/tree/HEAD/lib/matplotlib/mpl-data/stylelib

from __future__ import division, print_function
from distutils.version import LooseVersion
import re

import matplotlib
from viscid import logger
from viscid.compat import unicode  # pylint: disable=redefined-builtin
from viscid.plot import _cm_cubehelix  # pylint: disable=unused-import
from viscid.plot import _cm_listed  # pylint: disable=unused-import


# Set these in your RC file to
use_styles = []
rc_params = {}
rc = {}

# setup viscid-specific matplotlib rc entries
viscid_mpl_rc_params = {
    u"viscid.cbarfmt": [u"", unicode],
    u"viscid.majorfmt": [u"", unicode],
    u"viscid.minorfmt": [u"", unicode],
    u"viscid.majorloc": [u"", unicode],
    u"viscid.minorloc": [u"", unicode],
    u"viscid.symmetric_cmap": [u"", unicode]
}
for key, default_converter in viscid_mpl_rc_params.items():
    matplotlib.defaultParams[key] = default_converter
    matplotlib.rcParams.validate[key] = default_converter[1]
    matplotlib.rcParamsDefault.validate[key] = default_converter[1]
    matplotlib.rcParams[key] = default_converter[0]
    matplotlib.rcParamsOrig[key] = default_converter[0]
    matplotlib.rcParamsDefault[key] = default_converter[0]

VISCID_STYLES = {
    #######################
    u"viscid-default": u"""
image.cmap: viridis
viscid.symmetric_cmap: RdBu_r
""",
    u"viscid-colorblind": u"""
axes.prop_cycle: cycler('color', ['004358', 'FD7400', '3DA88E', \
                                  '83522B', '00D4FD', 'E2D893'])
""",
    #####################
    u"viscid-steve": u"""
viscid.cbarfmt: steve
"""
}

# hack the cycler stuff back to the pre-1.5.0 syntax
if LooseVersion(matplotlib.__version__) < LooseVersion("1.5.0"):
    for k, v in VISCID_STYLES.items():
        v = re.sub(r"(.*?)\.prop_cycle\s*:\s*cycler\((['\"])(.*?)\2,\s*"
                   r"\[\s*(.*)\s*\]\s*\)",
                   r"\1.\3_cycle: \4", v)
        v = v.replace("'", "").replace('"', "")
        VISCID_STYLES[k] = v


def inject_viscid_styles(show_warning=True):
    try:
        import tempfile
        import os

        from matplotlib import rc_params_from_file, style

        tmpfname = tempfile.mkstemp()[1]
        for style_name, text in VISCID_STYLES.items():
            with open(tmpfname, 'w') as f:
                f.write(text)
            params = rc_params_from_file(tmpfname, use_default_template=False)
            style.library[style_name] = params
        os.unlink(tmpfname)
        style.reload_library()
    except ImportError:
        if show_warning:
            logger.debug("Upgrade to matplotlib >= 1.5.0 to use style sheets")

def post_rc_actions(show_warning=True):
    try:
        from matplotlib import style

        if u"viscid-default" not in use_styles:
            use_styles.insert(0, u"viscid-default")

        for s in use_styles:
            try:
                style.use(s)
            except ValueError as e:
                logger.warn(str(e))
    except ImportError:
        if show_warning and use_styles:
            logger.warn("Upgrade to matplotlib >= 1.5.0 to use style sheets")

    matplotlib.rcParams.update(rc_params)
    for group, params in rc.items():
        matplotlib.rc(group, **params)

inject_viscid_styles()
post_rc_actions(show_warning=False)

##
## EOF
##
