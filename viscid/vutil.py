#!/usr/bin/env python

# FIXME: this module is way too long and disorganized

from __future__ import print_function, division

import fnmatch
from glob import glob
from itertools import chain
import logging
from operator import itemgetter
import os.path
import re
import sys
from timeit import default_timer as time

import viscid
from viscid import logger
from viscid import sliceutil
from viscid.compat import izip

import numpy as np


__all__ = ["timeit", "resolve_path", "find_item", "find_items",
           "get_trilinear_field", "slice_globbed_filenames", "glob2",
           "interact"]


tree_prefix = ".   "


def find_field(vfile, fld_name_lst):
    """ convenience function to get a field that could be called many things
    returns the first fld_name in the list that is in the file """
    for fld_name in fld_name_lst:
        if fld_name in vfile:
            return vfile[fld_name]
    raise KeyError("file {0} contains none of {1}".format(vfile, fld_name_lst))

def split_floats(arg_str):
    return [float(s) for s in arg_str.split(',')]

def add_animate_arguments(parser):
    """ add common options for animating, you may want to make sure parser was
    constructed with conflict_handler='resolve' """
    anim = parser.add_argument_group("Options for creating animations")
    anim.add_argument("-a", "--animate", default=None,
                      help="animate results")
    anim.add_argument("--prefix", default=None,
                      help="Prefix of the output image filenames")
    anim.add_argument('-r', '--rate', dest='framerate', type=int, default=5,
                      help="animation frame rate (default 5).")
    anim.add_argument('--qscale', dest='qscale', default='2',
                      help="animation quality flag (default 2).")
    anim.add_argument('-k', dest='keep', action='store_true',
                      help="keep temporary files.")
    return parser

def add_mpl_output_arguments(parser):
    """ add common options for tuning matplotlib output, you may want to make
    sure parser was constructed with conflict_handler='resolve' """
    mplargs = parser.add_argument_group("Options for tuning matplotlib")
    mplargs.add_argument("-s", "--size", dest="plot_size", type=split_floats,
                         default=None, help="size of mpl plot (inches)")
    mplargs.add_argument("--dpi", dest="dpi", type=float, default=None,
                         help="dpi of plot")
    parser.add_argument("--prefix", default=None,
                        help="Prefix of the output image filenames")
    parser.add_argument("--format", "-f", default="png",
                        help="output format, as in 'png'|'pdf'|...")
    parser.add_argument('-w', '--show', dest='show', action="store_true",
                        help="show plots with plt.show()")
    return parser

def common_argparse(parser, default_verb=0):
    """ add some common verbosity stuff to argparse, parse the
    command line args, and setup the logging levels
    parser should be an ArgumentParser instance, and kwargs
    should be options that get passed to logger.basicConfig
    returns the args namespace  """
    general = parser.add_argument_group("Viscid general options")
    general.add_argument("--log", action="store", type=str, default=None,
                         help="Logging level (overrides verbosity)")
    general.add_argument("-v", action="count", default=default_verb,
                         help="increase verbosity")
    general.add_argument("-q", action="count", default=0,
                         help="decrease verbosity")
    args = parser.parse_args()

    # setup the logging level
    if args.log is not None:
        logger.setLevel(getattr(logging, args.log.upper()))
    else:
        # default = 30 WARNING
        verb = args.v - args.q
        logger.setLevel(int(30 - 10 * verb))

    return args

def subclass_spider(cls):
    """ return recursive list of subclasses of cls (depth first) """
    lst = [cls]
    # reversed gives precedence to the more recently declared classes
    for c in reversed(cls.__subclasses__()):
        lst += subclass_spider(c)
    return lst

def timereps(reps, func, *args, **kwargs):
    arr = [None] * reps
    for i in range(reps):
        start = time()
        func(*args, **kwargs)
        end = time()
        arr[i] = end - start
    return min(arr), max(arr), sum(arr) / reps

def timeit(f, *args, **kwargs):
    """overly simple timeit wrapper

    Arguments:
        f: callable to timeit
        *args: positional arguments for `f`
        **kwargs: keyword arguments for `f`

    Keyword arguments:
        timeit_repeat (int): number of times to call `f` (Default: 1)
        timeit_print_stats (bool): print min/max/mean/median when done
        timeit_quet (bool): quiets all output (useful if you only want
            the timeit_stats dict filled)
        timeit_stats (dict): Stats will be stuffed into here

    Returns:
        The result of `f(*args, **kwargs)`
    """
    timeit_repeat = kwargs.pop('timeit_repeat', 1)
    timeit_print_stats = kwargs.pop('timeit_print_stats', True)
    timeit_quiet = kwargs.pop('timeit_quiet', False)
    timeit_stats = kwargs.pop('timeit_stats', dict())

    times = np.empty((timeit_repeat,), dtype='f8')

    for i in range(timeit_repeat):
        ret = None
        t0 = time()
        ret = f(*args, **kwargs)
        t1 = time()

        s = "{0:.03g}".format(t1 - t0)
        times[i] = t1 - t0
        if not timeit_quiet and (timeit_repeat == 1 or not timeit_print_stats):
            secs = "second" if s == "1" else "seconds"
            print("<function {0}.{1}>".format(f.__module__, f.__name__),
                  "took", s, secs)

    timeit_stats['min'] = np.min(times)
    timeit_stats['max'] = np.max(times)
    timeit_stats['mean'] = np.mean(times)
    timeit_stats['median'] = np.median(times)
    timeit_stats['repeat'] = timeit_repeat

    if not timeit_quiet and timeit_repeat > 1 and timeit_print_stats:
        print("<function {0}.{1}> stats ({2} runs):"
              "".format(f.__module__, f.__name__, timeit_repeat))
        print("  Min: {min:.3g}, Mean: {mean:.3g}, Median: {median:.3g}, "
              "Max: {max:.3g}".format(**timeit_stats))

    return ret

def resolve_path(dset, loc, first=False):
    """Search for globbed paths in a nested dict-like hierarchy

    Args:
        dset (dict): Root of some nested dict-like hierarchy
        loc (str): path as a glob pattern
        first (bool): Stop at first match and return a single value

    Raises:
        KeyError: If there are no glob matches

    Returns:
        If first == True, (value, path)
        else, ([value0, value1, ...], [path0, path1, ...])
    """
    try:
        if first:
            return dset[loc], loc
        else:
            return [dset[loc]], [loc]
    except KeyError:
        searches = [loc.strip('/').split('/')]
        dsets = [dset]
        paths = [[]]

        while any(searches):
            next_dsets = []
            next_searches = []
            next_paths = []
            for dset, search, path in izip(dsets, searches, paths):
                try:
                    next_dsets.append(dset[search[0]])
                    next_searches.append(search[1:])
                    next_paths.append(path + [search[0]])
                except (KeyError, TypeError, IndexError):
                    s = [{}.items()]
                    if hasattr(dset, 'items'):
                        s.append(dset.items())
                    if hasattr(dset, 'attrs'):
                        s.append(dset.attrs.items())
                    for key, val in chain(*s):
                        if fnmatch.fnmatchcase(key, search[0]):
                            next_dsets.append(val)
                            next_searches.append(search[1:])
                            next_paths.append(path + [key])
                            if first:
                                break
            dsets = next_dsets
            searches = next_searches
            paths = next_paths

    if dsets:
        dsets, paths = dsets, ['/'.join(p) for p in paths]
        if first:
            return dsets[0], paths[0]
        else:
            return dsets, paths
    else:
        raise KeyError("Path {0} has no matches".format(loc))

def find_item(dset, loc):
    """Shortcut for first :py:func:`resolve_path`, item only"""
    return resolve_path(dset, loc, first=True)[0]

def find_items(dset, loc):
    """Shortcut for :py:func:`resolve_path`, items only"""
    return resolve_path(dset, loc)[0]

def str_to_value(s):
    ret = s
    s_clean = s.strip().lower()

    if len(s_clean) == 0 or s_clean == "none":
        ret = None
    elif s_clean == "true":
        ret = True
    elif s_clean == "false":
        ret = True
    elif s_clean == "True":
        ret = True
    else:
        try:
            ret = int(s_clean)
        except ValueError:
            try:
                ret = float(s_clean)
            except ValueError:
                pass
    return ret

def prepare_lines(lines, scalars=None, do_connections=False, other=None):
    """Concatenate and standardize a list of lines

    Args:
        lines (list): Must be a list of 3xN or 4xN ndarrays of xyz(s)
            data for N points along the line. N need not be the same
            for all lines. Can alse be 6xN such that lines[:][3:, :]
            are interpreted as rgb colors
        scalars (ndarray, list): Can have shape 1xN for a single scalar
            or 3xN for an rgb color for each point. If the shape is
            1xNlines, the scalar is broadcast so the whole line gets
            the same value, and likewise for 3xNlines and rgb colors.
            Can also be a list of hex color (#ffffff) strings.
            Otherwise, scalars is reshaped to -1xN.
        do_connections (bool): Whether or not to make connections array
        other (dict): a dictionary of other arrays that should be
            reshaped and the like the same way scalars is

    Returns:
        (vertices, scalars, connections, other)

        * vertices (ndarray): 3xN array of N xyz points. N is the sum
            of the lengths of all the lines
        * scalars (ndarray): N array of scalars, 3xN array of uint8
            rgb values, or None
        * connections (ndarray): Nx2 array of ints (indices along
            axis 1 of vertices) describing the forward and backward
            connectedness of the lines, or None
        * other (dict): a dict of N length arrays

    Raises:
        ValueError: If rgb data is not in a valid range or the shape
            of scalars is not understood
    """
    nlines = len(lines)
    npts = [line.shape[1] for line in lines]
    N = np.sum(npts)
    first_idx = np.cumsum([0] + npts[:-1])
    vertices = [np.asarray(line) for line in lines]
    vertices = np.concatenate(lines, axis=1)
    if vertices.dtype.kind not in 'fc':
        vertices = np.asarray(vertices, dtype='f')

    if vertices.shape[0] > 3:
        if scalars is not None:
            viscid.logger.warn("Overriding line scalars with scalars kwarg")
        else:
            scalars = vertices[3:, :]
        vertices = vertices[:3, :]

    if scalars is not None:
        if isinstance(scalars, viscid.field.Field):
            scalars = viscid.interp_trilin(scalars, vertices)
            if scalars.size != N:
                raise ValueError("Scalars was not a scalar field")
        elif isinstance(scalars, (list, tuple)):
            try:
                scalars = np.concatenate(scalars)
            except ValueError:
                scalars_asarr = np.asarray(scalars)
                if scalars_asarr.dtype.kind in ('S', 'U'):
                    scalars = scalars_asarr
                else:
                    raise

        scalars = np.atleast_2d(scalars)

        if scalars.shape == (1, 1):
            scalars = scalars.repeat(N, axis=1)
        elif scalars.shape == (1, nlines) or scalars.shape == (nlines, 1):
            # one scalar for each line, so broadcast it
            scalars = scalars.reshape(nlines, 1)
            scalars = [scalars[i].repeat(ni) for i, ni in enumerate(npts)]
            scalars = np.concatenate(scalars, axis=0).reshape(1, N)
        elif scalars.shape == (N, 1) or scalars.shape == (1, N):
            # catch these so they're not interpreted as colors if
            # nlines == 1 and N == 3; ie. 1 line with 3 points
            scalars = scalars.reshape(1, N)
        elif scalars.shape == (3, nlines) or scalars.shape == (nlines, 3):
            # one rgb color for each line, so broadcast it
            if scalars.shape == (3, nlines):
                scalars = scalars.T
            colors = []
            for i, ni in enumerate(npts):
                c = scalars[i].reshape(3, 1).repeat(ni, axis=1)
                colors.append(c)
            scalars = np.concatenate(colors, axis=1)
        else:
            scalars = scalars.reshape(-1, N)

        if scalars.dtype.kind in ['S', 'U']:
            # translate hex colors (#ff00ff) into rgb values
            scalars = np.char.lstrip(scalars, '#').astype('S6')
            scalars = np.char.zfill(scalars, 6)
            # this np.char.decode(..., 'hex') doesn't work for py3k; kinda silly
            try:
                scalars = np.frombuffer(np.char.decode(scalars, 'hex'), dtype='u1')
            except LookupError:
                import codecs
                scalars = np.frombuffer(codecs.decode(scalars, 'hex_codec'),
                                        dtype='u1')
            scalars = scalars.reshape(-1, 3).T
        elif scalars.shape[0] == 1:
            # normal scalars
            scalars = scalars.reshape(-1)
        elif scalars.shape[0] == 3:
            # The scalars encode rgb data, standardize the result to a
            # 3xN ndarray of 1 byte unsigned ints (chars)
            if np.all(scalars >= 0) and np.all(scalars <= 1):
                scalars = (255 * scalars).round().astype('u1')
            elif np.all(scalars >= 0) and np.all(scalars < 256):
                scalars = scalars.round().astype('u1')
            else:
                raise ValueError("Rgb data should be in range [0, 1] or "
                                 "[0, 255], range given is [{0}, {1}]"
                                 "".format(np.min(scalars), np.max(scalars)))
        else:
            raise ValueError("Scalars should either be a number, or set of "
                             "rgb values, shape is {0}".format(scalars.shape))

    # broadcast / reshape additional arrays given in other
    if other:
        for key, arr in other.items():
            if arr is None:
                pass
            elif arr.shape == (1, nlines) or arr.shape == (nlines, 1):
                arr = arr.reshape(nlines, 1)
                arr = [arr[i].repeat(ni) for i, ni in enumerate(npts)]
                other[key] = np.concatenate(arr, axis=0).reshape(1, N)
            else:
                try:
                    other[key] = arr.reshape(-1, N)
                except ValueError:
                    viscid.logger.warn("Unknown dimension, dropping array {0}"
                                       "".format(key))

    if do_connections:
        connections = [None] * nlines
        for i, ni in enumerate(npts):
            # i0 is the index of the first point of the i'th line in lines
            i0 = first_idx[i]
            connections[i] = np.vstack([np.arange(i0, i0 + ni - 1.5),
                                        np.arange(i0 + 1, i0 + ni - 0.5)]).T
        connections = np.concatenate(connections, axis=0).astype('i')
    else:
        connections = None

    return vertices, scalars, connections, other

def get_trilinear_field():
    """get a generic trilinear field"""
    xl, xh, nx = -1.0, 1.0, 41
    yl, yh, ny = -1.5, 1.5, 41
    zl, zh, nz = -2.0, 2.0, 41
    x = np.linspace(xl, xh, nx)
    y = np.linspace(yl, yh, ny)
    z = np.linspace(zl, zh, nz)
    crds = viscid.wrap_crds("nonuniform_cartesian",
                            [('x', x), ('y', y), ('z', z)])
    b = viscid.empty(crds, name="f", nr_comps=3, center="Cell",
                     layout="interlaced")
    X, Y, Z = b.get_crds(shaped=True)

    x01, y01, z01 = 0.5, 0.5, 0.5
    x02, y02, z02 = 0.5, 0.5, 0.5
    x03, y03, z03 = 0.5, 0.5, 0.5

    b['x'][:] = (0.0 + 1.0 * (X - x01) + 1.0 * (Y - y01) + 1.0 * (Z - z01) +
                 1.0 * (X - x01) * (Y - y01) + 1.0 * (Y - y01) * (Z - z01) +
                 1.0 * (X - x01) * (Y - y01) * (Z - z01))
    b['y'][:] = (0.0 + 1.0 * (X - x02) - 1.0 * (Y - y02) + 1.0 * (Z - z02) +
                 1.0 * (X - x02) * (Y - y02) + 1.0 * (Y - y02) * (Z - z02) -
                 1.0 * (X - x02) * (Y - y02) * (Z - z02))
    b['z'][:] = (0.0 + 1.0 * (X - x03) + 1.0 * (Y - y03) - 1.0 * (Z - z03) +
                 1.0 * (X - x03) * (Y - y03) + 1.0 * (Y - y03) * (Z - z03) +
                 1.0 * (X - x03) * (Y - y03) * (Z - z03))
    return b

def slice_globbed_filenames(glob_pattern):
    """Apply a slice to a glob pattern

    Note:
        Slice by value works by adding an 'f' to a value, as like the
        rest of Viscid.

    Args:
        glob_pattern (str): A string

    Returns:
        list of filenames

    Examples:
        If a directory contains files,

        >>> os.listdir()
        ["file.010.txt", "file.020.txt", "file.030.txt", "file.040.txt"]

        then sliced globs can look like

        >>> expand_glob_slice("f*.[:2].txt")
        ["file.010.txt", "file.020.txt"]

        >>> expand_glob_slice("f*.[10.0f::2].txt")
        ["file.010.txt", "file.030.txt"]

        >>> expand_glob_slice("f*.[20f:2].txt")
        ["file.020.txt", "file.040.txt"]
    """
    glob_pattern = os.path.expanduser(os.path.expandvars(glob_pattern))
    glob_pattern = os.path.abspath(glob_pattern)

    # construct a regex to match the results
    # verify glob pattern has only one
    number_re = r"(?:[-+]?[0-9]*\.?[0-9]+f?|[-+]?[0-9+])"
    slc_re = r"\[({0})?(:({0})?){{0,2}}\]".format(number_re)
    n_slices = len(re.findall(slc_re, glob_pattern))

    if n_slices > 1:
        viscid.logger.warn("Multiple filename slices found, only using the "
                           "first.")

    if n_slices:
        m = re.search(slc_re, glob_pattern)
        slcstr = glob_pattern[m.start() + 1:m.end() - 1]
        edited_glob = glob_pattern[:m.start()] + "*" + glob_pattern[m.end():]
        res_re = glob_pattern[:m.start()] + "TSLICE" + glob_pattern[m.end():]
        res_re = fnmatch.translate(res_re)
        res_re = res_re.replace("TSLICE", r"(?P<TSLICE>.*?)")
    else:
        edited_glob = glob_pattern
        slcstr = ""

    fnames = glob(edited_glob)

    if n_slices:
        if not fnames:
            raise IOError("the glob {0} matched no files".format(edited_glob))

        times = []
        _newfn = []
        for fn in fnames:
            try:
                times.append(float(re.match(res_re, fn).group('TSLICE')))
                _newfn.append(fn)
            except ValueError:
                pass
        fnames = _newfn
        times = [float(re.match(res_re, fn).group('TSLICE')) for fn in fnames]
        fnames = [fn for fn, t in sorted(zip(fnames, times), key=itemgetter(1))]
        times.sort()
        slc = sliceutil.to_slice(times, slcstr)
    else:
        times = [None] * len(fnames)
        slc = slice(None)

    return fnames[slc]


def glob2(glob_pattern, *args, **kwargs):
    """Wrap slice_globbed_filenames, but return [] on no match

    See Also:
        * :py:func:`slice_globbed_filenames`
    """
    try:
        return slice_globbed_filenames(glob_pattern, *args, **kwargs)
    except IOError:
        return []

def interact(banner=None, ipython=True, stack_depth=0, global_ns=None,
             local_ns=None, viscid_ns=True, mpl_ns=False, mvi_ns=False):
    """Start an interactive interpreter"""
    if banner is None:
        banner = "Interactive Viscid..."
        if mpl_ns:
            banner += "\n  - Viscid's matplotlib interface available as `vlt`"
        if mvi_ns:
            banner += "\n  - Viscid's mayavi interface available as `vlab`"
            banner += "\n  - Use vlab.show(...) to interact with Mayavi"
            banner += "\n  - FYI, all Mayavi objects all have trait_names()"
        banner += "\n  - Use Ctrl-D (eof) to end interaction"

    def _merge_ns(src, target):
        target.update(dict([(name, getattr(src, name)) for name in dir(src)]))
        target[src.__name__.split('.')[-1]] = src

    ns = dict()

    if viscid_ns:
        _merge_ns(viscid, ns)
    if mpl_ns:
        from viscid.plot import vpyplot as vlt
        _merge_ns(vlt, ns)
    if mvi_ns:
        from viscid.plot import vlab
        _merge_ns(vlab, ns)

    call_frame = sys._getframe(stack_depth).f_back  # pylint: disable=protected-access

    if global_ns is None:
        global_ns = call_frame.f_globals
    ns.update(global_ns)

    if local_ns is None:
        local_ns = call_frame.f_locals
    ns.update(local_ns)

    try:
        if not ipython:
            raise ImportError
        from IPython import embed
        embed(user_ns=ns, banner1=banner)
    except ImportError:
        import code
        code.interact(banner, local=ns)
    print("Resuming Script")

##
## EOF
##
