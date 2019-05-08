import os
import sys
import shutil
import fnmatch
import requests
import zipfile
import json
from collections import defaultdict
from io import BytesIO, StringIO
from configparser import SafeConfigParser
from datetime import datetime

from paver.easy import *
# this pulls in the sphinx target
from paver.doctools import html


options(
    plugin = Bunch(
        name = 'geogig',
        ext_libs = path('geogig/extlibs'),
        ext_src = path('geogig/ext-src'),
        source_dir = path('geogig'),
        tmppackage_dir = path('tmppackage'),
        package_dir = path('.'),
        tests = ['tests'],
        excludes = [
            'ext-src',
            '*.pyc',
            'metadata.txt',
            'setuptools',
            'pkg_resources',
            'doctools.js'
        ],
        # skip certain files inadvertently found by exclude pattern globbing
        skip_exclude=[],
    ),

    sphinx = Bunch(
        docroot = path('docs'),
        sourcedir = path('docs/source'),
        builddir = path('docs/build')
    )
)

@task
@cmdopts([
    ('clean', 'c', 'clean out dependencies first'),
])
def setup(options):
    clean = getattr(options, 'clean', False)
    ext_libs = options.plugin.ext_libs
    ext_src = options.plugin.ext_src
    if clean:
        ext_libs.rmtree()
    ext_libs.makedirs()

    tmpCommonsPath = path(__file__).dirname() / "qgiscommons"
    dst = ext_libs / "qgiscommons2"
    if dst.exists():
        dst.rmtree()
    r = requests.get("https://github.com/boundlessgeo/lib-qgis-commons/archive/master.zip", stream=True)
    z = zipfile.ZipFile(BytesIO(r.content))
    z.extractall(path=tmpCommonsPath.abspath())
    src = tmpCommonsPath / "lib-qgis-commons-master" / "qgiscommons2"
    src.copytree(dst.abspath())
    tmpCommonsPath.rmtree()

    runtime, test = read_requirements()
    os.environ['PYTHONPATH']=ext_libs.abspath()
    for req in runtime + test:
        sh('pip3 install -U -t "%(ext_libs)s" %(dep)s' % {
            'ext_libs' : ext_libs.abspath(),
            'dep' : req
        })

def read_requirements():
    '''return a list of runtime and list of test requirements'''
    lines = open('requirements.txt').readlines()
    lines = [ l for l in [ l.strip() for l in lines] if l ]
    divider = '# test requirements'
    try:
        idx = lines.index(divider)
    except ValueError:
        raise BuildFailure('expected to find "%s" in requirements.txt' % divider)
    not_comments = lambda s,e: [ l for l in lines[s:e] if l[0] != '#']
    return not_comments(0, idx), not_comments(idx+1, None)

@task
def install(options):
    '''install plugin to qgis'''
    plugin_name = options.plugin.name
    src = path(__file__).dirname() / plugin_name
    if sys.platform == 'darwin':
        dst = path('~').expanduser() / "Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins" / plugin_name
    else:
        dst = path('~').expanduser() / "AppData/Roaming/QGIS/QGIS3/QGIS/QGIS3/profiles/default/python/plugins" / plugin_name
    src = src.abspath()
    dst = dst.abspath()
    if not hasattr(os, 'symlink'):
        dst.rmtree()
        src.copytree(dst)
    elif not dst.exists():
        src.symlink(dst)
        # Symlink the build folder to the parent
        docs = path('..') / '..' / "docs" / 'build' / 'html'
        docs_dest = path(__file__).dirname() / plugin_name / "docs"
        docs_link = docs_dest / 'html'
        if not docs_dest.exists():
            docs_dest.mkdir()
        if not docs_link.islink():
            docs.symlink(docs_link)

def copyAndOverwrite(src, dst):
    for src_dir, dirs, files in os.walk(src):
        dst_dir = src_dir.replace(src, dst, 1)
        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir)
        for file_ in files:
            src_file = os.path.join(src_dir, file_)
            dst_file = os.path.join(dst_dir, file_)
            if os.path.exists(dst_file):
                os.remove(dst_file)
            shutil.move(src_file, dst_dir)
@task
@cmdopts([
    ('tests', 't', 'Package tests with plugin'),
    ('win32', '', 'Package for windows 32 bits'),
    ('win64', '', 'Package for windows 64 bits'),
    ('linux', '', 'Package for linux'),
    ('mac', '', 'Package for mac'),
    ('multi', '', 'Package for all platforms')
])
def package(options):
    '''create package for plugin'''
    builddocs(options)
    src = options.plugin.source_dir
    metadata_file = src / "metadata.txt"
    cfg = SafeConfigParser()
    cfg.optionxform = str
    cfg.read(metadata_file)
    version = cfg.get('general', 'version')
    modifiers = {}
    options.plugin.tmppackage_dir.rmtree()
    if hasattr(options.package, 'win32') or hasattr(options.package, 'all'):
        modifiers["win32"] = "--platform win32 --no-deps"
    elif hasattr(options.package, 'win64') or hasattr(options.package, 'all'):
        modifiers["win64"] = "--platform win_amd64 --no-deps"
    if hasattr(options.package, 'linux') or hasattr(options.package, 'all'):
        modifiers["linux"] = "--platform manylinux1_x86_64 --no-deps"
    if hasattr(options.package, 'mac') or hasattr(options.package, 'all'):
        modifiers["mac"] = "--platform macosx_10_10_x86_64 --no-deps"

    if not modifiers:
        platforms = ["win32", "win_amd64", "manylinux1_x86_64", "macosx_10_10_x86_64"]
        for platform in platforms:
            dst = options.plugin.tmppackage_dir / platform
            if platform == platforms[0]:
                src.copytree(dst)
            extlibs = dst / "extlibs"
            sh('pip3 install -U -t "%(ext_libs)s" --no-deps --platform %(platform)s protobuf==3.6.0' % {
                'ext_libs' : extlibs.abspath(),
                'platform' : platform
            })
        for platform in platforms[1:]:
            dst = options.plugin.tmppackage_dir / platforms[0]
            dstextlibs = dst / "extlibs"
            src = options.plugin.tmppackage_dir / platform
            srcextlibs = src / "extlibs"
            copyAndOverwrite(srcextlibs, dstextlibs)

        package_file = options.plugin.package_dir / ('%s_%s.zip' % (options.plugin.name, version))
        with zipfile.ZipFile(package_file, "w", zipfile.ZIP_DEFLATED) as zipf:
            if not hasattr(options.package, 'tests'):
                options.plugin.excludes.extend(options.plugin.tests)
            _make_zip(zipf, options, options.plugin.tmppackage_dir / platforms[0])
    else:
        dst = options.plugin.tmppackage_dir
        extlibs = dst / "extlibs"
        for name, mods in modifiers.items():
            src.copytree(dst)
            sh('pip3 install -U -t "%(ext_libs)s" %(modifiers)s protobuf==3.6.0' % {
                'ext_libs' : extlibs.abspath(),
                'modifiers' : mods
            })
            package_file = options.plugin.package_dir / ('%s_%s_%s.zip' % (options.plugin.name, name, version))
            with zipfile.ZipFile(package_file, "w", zipfile.ZIP_DEFLATED) as zipf:
                if not hasattr(options.package, 'tests'):
                    options.plugin.excludes.extend(options.plugin.tests)
                _make_zip(zipf, options, dst)
            dst.rmtree()
    options.plugin.tmppackage_dir.rmtree()

def _make_zip(zipFile, options, srcDir):
    metadata_file = options.plugin.source_dir / "metadata.txt"
    cfg = SafeConfigParser()
    cfg.optionxform = str
    cfg.read(metadata_file)
    base_version = cfg.get('general', 'version')
    head_path = path('.git/HEAD')
    head_ref = head_path.open('rU').readline().strip()[5:]
    ref_file = path(".git/" + head_ref)
    ref = ref_file.open('rU').readline().strip()
    cfg.set("general", "version", "%s-%s-%s" % (base_version, datetime.now().strftime("%Y%m%d"), ref))

    buf = StringIO()
    cfg.write(buf)
    zipFile.writestr(os.path.join(options.plugin.name,"metadata.txt"), buf.getvalue())

    excludes = set(options.plugin.excludes)
    skips = options.plugin.skip_exclude

    exclude = lambda p: any([path(p).fnmatch(e) for e in excludes])
    def filter_excludes(root, items):
        if not items:
            return []
        # to prevent descending into dirs, modify the list in place
        for item in list(items):  # copy list or iteration values change
            itempath = path(os.path.relpath(root)) / item
            if exclude(item) and item not in skips:
                debug('Excluding %s' % itempath)
                items.remove(item)
        return items

    for root, dirs, files in os.walk(srcDir):
        for f in filter_excludes(root, files):
            relpath = os.path.join(options.plugin.name, os.path.relpath(root, srcDir))
            zipFile.write(path(root) / f, path(relpath) / f)
        filter_excludes(root, dirs)

    for root, dirs, files in os.walk(options.sphinx.builddir):
        for f in files:
           if f not in excludes:
                relpath = os.path.join(options.plugin.name, "docs", os.path.relpath(root, options.sphinx.builddir))
                zipFile.write(path(root) / f, path(relpath) / f)


def create_settings_docs(options):
    settings_file = path(options.plugin.name) / "settings.json"
    doc_file = options.sphinx.sourcedir / "settingsconf.rst"
    try:
        with open(settings_file) as f:
            settings = json.load(f)
    except:
        return
    grouped = defaultdict(list)
    for setting in settings:
        grouped[setting["group"]].append(setting)
    with open (doc_file, "w") as f:
        f.write(".. _plugin_settings:\n\n"
                "Plugin settings\n===============\n\n"
                "The plugin can be adjusted using the following settings, "
                "to be found in its settings dialog (|path_to_settings|).\n")
        for groupName, group in grouped.items():
            section_marks = "-" * len(groupName)
            f.write("\n%s\n%s\n\n"
                    ".. list-table::\n"
                    "   :header-rows: 1\n"
                    "   :stub-columns: 1\n"
                    "   :widths: 20 80\n"
                    "   :class: non-responsive\n\n"
                    "   * - Option\n"
                    "     - Description\n"
                    % (groupName, section_marks))
            for setting in group:
                f.write("   * - %s\n"
                        "     - %s\n"
                        % (setting["label"], setting["description"]))


@task
@cmdopts([
    ('clean', 'c', 'clean out built artifacts first'),
    ('sphinx_theme=', 's', 'Sphinx theme to use in documentation'),
])
def builddocs(options):
    try:
        # May fail if not in a git repo
        sh("git submodule init")
        sh("git submodule update")
    except:
        pass
    create_settings_docs(options)
    if getattr(options, 'clean', False):
        options.sphinx.builddir.rmtree()
    if getattr(options, 'sphinx_theme', False):
        # overrides default theme by the one provided in command line
        set_theme = "-D html_theme='{}'".format(options.sphinx_theme)
    else:
        # Uses default theme defined in conf.py
        set_theme = ""
    sh("sphinx-build -a {} {} {}/html".format(set_theme,
                                              options.sphinx.sourcedir,
                                              options.sphinx.builddir))

@task
def install_devtools():
    """Install development tools
    """
    try:
        import pip
    except:
        error('FATAL: Unable to import pip, please install it first!')
        sys.exit(1)

    pip.main(['install', '-r', 'requirements-dev.txt'])


@task
@consume_args
def pep8(args):
    """Check code for PEP8 violations
    """
    try:
        import pep8
    except:
        error('pep8 not found! Run "paver install_devtools".')
        sys.exit(1)

    # Errors to ignore
    ignore = ['E203', 'E121', 'E122', 'E123', 'E124', 'E125', 'E126', 'E127',
        'E128', 'E402']
    styleguide = pep8.StyleGuide(ignore=ignore,
                                 exclude=['*/extlibs/*', '*/ext-src/*'],
                                 repeat=True, max_line_length=79,
                                 parse_argv=args)
    styleguide.input_dir(options.plugin.source_dir)
    info('===== PEP8 SUMMARY =====')
    styleguide.options.report.print_statistics()


@task
@consume_args
def autopep8(args):
    """Format code according to PEP8
    """
    try:
        import autopep8
    except:
        error('autopep8 not found! Run "paver install_devtools".')
        sys.exit(1)

    if any(x not in args for x in ['-i', '--in-place']):
        args.append('-i')

    args.append('--ignore=E261,E265,E402,E501')
    args.insert(0, 'dummy')

    cmd_args = autopep8.parse_args(args)

    excludes = ('extlib', 'ext-src')
    for p in options.plugin.source_dir.walk():
        if any(exclude in p for exclude in excludes):
            continue

        if p.fnmatch('*.py'):
            autopep8.fix_file(p, options=cmd_args)


@task
@consume_args
def pylint(args):
    """Check code for errors and coding standard violations
    """
    try:
        from pylint import lint
    except:
        error('pylint not found! Run "paver install_devtools".')
        sys.exit(1)

    if not 'rcfile' in args:
        args.append('--rcfile=pylintrc')

    args.append(options.plugin.source_dir)
    lint.Run(args)
