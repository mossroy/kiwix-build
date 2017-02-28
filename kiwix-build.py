#!/usr/bin/env python3

import os, sys, stat
import argparse
import urllib.request
import subprocess
import platform
from collections import OrderedDict

from dependencies import Dependency
from utils import (
    pj,
    remove_duplicates,
    get_sha256,
    StopBuild,
    SkipCommand,
    Defaultdict)

REMOTE_PREFIX = 'http://download.kiwix.org/dev/'

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

CROSS_ENV = {
    'fedora_win32': {
        'toolchain_names': ['mingw32_toolchain'],
        'root_path': '/usr/i686-w64-mingw32/sys-root/mingw',
        'properties': {
            'c_link_args': ['-lwinmm', '-lws2_32', '-lshlwapi', '-lrpcrt4'],
            'cpp_link_args': ['-lwinmm', '-lws2_32', '-lshlwapi', '-lrpcrt4']
        },
        'host_machine': {
            'system': 'windows',
            'cpu_family': 'x86',
            'cpu': 'i686',
            'endian': 'little'
        },
        'env': {
            '_format_PKG_CONFIG_LIBDIR': '{root_path}/lib/pkgconfig'
        }
    },
    'debian_win32': {
        'toolchain_names': ['mingw32_toolchain'],
        'root_path': '/usr/i686-w64-mingw32/',
        'properties': {
            'c_link_args': ['-lwinmm', '-lws2_32', '-lshlwapi', '-lrpcrt4'],
            'cpp_link_args': ['-lwinmm', '-lws2_32', '-lshlwapi', '-lrpcrt4']
        },
        'host_machine': {
            'system': 'windows',
            'cpu_family': 'x86',
            'cpu': 'i686',
            'endian': 'little'
        },
        'env': {
            '_format_PKG_CONFIG_LIBDIR': '{root_path}/lib/pkgconfig'
        }
    }
}


PACKAGE_NAME_MAPPERS = {
    'fedora_native_dyn': {
        'COMMON': ['gcc-c++', 'cmake', 'automake', 'ccache'],
        'uuid': ['libuuid-devel'],
        'xapian-core': None, # Not the right version on fedora 25
        'ctpp2': None,
        'pugixml': None, # ['pugixml-devel'] but package doesn't provide pkg-config file
        'libmicrohttpd': ['libmicrohttpd-devel'],
        'zlib': ['zlib-devel'],
        'lzma': ['xz-devel'],
        'icu4c': None,
        'zimlib': None,
    },
    'fedora_native_static': {
        'COMMON': ['gcc-c++', 'cmake', 'automake', 'glibc-static', 'libstdc++-static', 'ccache'],
        'zlib': ['zlib-devel', 'zlib-static'],
        'lzma': ['xz-devel', 'xz-static']
        # Either there is no packages, or no static or too old
    },
    'fedora_win32_dyn': {
        'COMMON': ['mingw32-gcc-c++', 'mingw32-bzip2', 'mingw32-win-iconv', 'mingw32-winpthreads', 'wine', 'ccache'],
        'zlib': ['mingw32-zlib'],
        'lzma': ['mingw32-xz-libs'],
        'libmicrohttpd': ['mingw32-libmicrohttpd'],
    },
    'fedora_win32_static': {
        'COMMON': ['mingw32-gcc-c++', 'mingw32-bzip2-static', 'mingw32-win-iconv-static', 'mingw32-winpthreads-static', 'wine', 'ccache'],
        'zlib': ['mingw32-zlib-static'],
        'lzma': ['mingw32-xz-libs-static'],
        'libmicrohttpd': None, # ['mingw32-libmicrohttpd-static'] packaging dependecy seems buggy, and some static lib are name libfoo.dll.a and
                               # gcc cannot found them.
    },
    'debian_native_dyn': {
        'COMMON': ['gcc', 'cmake', 'libbz2-dev', 'ccache'],
        'zlib': ['zlib1g-dev'],
        'uuid': ['uuid-dev'],
        'ctpp2': ['libctpp2-dev'],
        'libmicrohttpd': ['libmicrohttpd-dev', 'ccache']
    },
    'debian_native_static': {
        'COMMON': ['gcc', 'cmake', 'libbz2-dev', 'ccache'],
        'zlib': ['zlib1g-dev'],
        'uuid': ['uuid-dev'],
        'ctpp2': ['libctpp2-dev'],
    },
    'debian_win32_dyn': {
        'COMMON': ['g++-mingw-w64-i686', 'gcc-mingw-w64-i686', 'gcc-mingw-w64-base', 'mingw-w64-tools', 'ccache']
    },
    'debian_win32_static': {
        'COMMON': ['g++-mingw-w64-i686', 'gcc-mingw-w64-i686', 'gcc-mingw-w64-base', 'mingw-w64-tools', 'ccache']
    },
}


def which(name):
    command = "which {}".format(name)
    output = subprocess.check_output(command, shell=True)
    return output[:-1].decode()


class BuildEnv:
    build_targets = ['native', 'win32']

    def __init__(self, options, targetsDict):
        self.source_dir = pj(options.working_dir, "SOURCE")
        build_dir = "BUILD_{target}_{libmod}".format(
            target=options.build_target,
            libmod='static' if options.build_static else 'dyn'
        )
        self.build_dir = pj(options.working_dir, build_dir)
        self.archive_dir = pj(options.working_dir, "ARCHIVE")
        self.log_dir = pj(options.working_dir, 'LOGS')
        self.install_dir = pj(self.build_dir, "INSTALL")
        for d in (self.source_dir,
                  self.build_dir,
                  self.archive_dir,
                  self.log_dir,
                  self.install_dir):
            os.makedirs(d, exist_ok=True)
        self.detect_platform()
        self.ninja_command = self._detect_ninja()
        if not self.ninja_command:
            sys.exit("ERROR: ninja command not found")
        self.meson_command = self._detect_meson()
        if not self.meson_command:
            sys.exit("ERROR: meson command not fount")
        self.setup_build(options.build_target)
        self.setup_toolchains()
        self.options = options
        self.libprefix = options.libprefix or self._detect_libdir()
        self.targetsDict = targetsDict

    def detect_platform(self):
        _platform = platform.system()
        self.distname = _platform
        if _platform == 'Windows':
            print('ERROR: kiwix-build is not intented to run on Windows platform.\n'
                  'It should probably not work, but well, you still can have a try.')
            cont = input('Do you want to continue ? [y/N]')
            if cont.lower() != 'y':
                sys.exit(0)
        if _platform == 'Darwin':
            print('WARNING: kiwix-build has not been tested on MacOS platfrom.\n'
                  'Tests, bug reports and patches are welcomed.')
        if _platform == 'Linux':
            self.distname, _, _ = platform.linux_distribution()
            self.distname = self.distname.lower()
            if self.distname == 'ubuntu':
                self.distname = 'debian'

    def setup_build(self, target):
        self.build_target = target
        if target == 'native':
            self.cross_env = {}
        else:
            cross_name = "{host}_{target}".format(
                host = self.distname,
                target = self.build_target)
            try:
                self.cross_env = CROSS_ENV[cross_name]
            except KeyError:
                sys.exit("ERROR : We don't know how to set env to compile"
                         " a {target} version on a {host} host.".format(
                            target = self.build_target,
                            host = self.distname
                        ))

    def setup_toolchains(self):
        toolchain_names = self.cross_env.get('toolchain_names', [])
        self.toolchains =[Toolchain.all_toolchains[toolchain_name](self)
                              for toolchain_name in toolchain_names]

    def finalize_setup(self):
        getattr(self, 'setup_{}'.format(self.build_target))()

    def setup_native(self):
        self.cmake_crossfile = None
        self.meson_crossfile = None

    def _gen_crossfile(self, name):
        crossfile = pj(self.build_dir, name)
        template_file = pj(SCRIPT_DIR, 'templates', name)
        with open(template_file, 'r') as f:
            template = f.read()
        content = template.format(
            toolchain=self.toolchains[0],
            **self.cross_env
        )
        with open(crossfile, 'w') as outfile:
            outfile.write(content)
        return crossfile

    def setup_win32(self):
        self.cmake_crossfile = self._gen_crossfile('cmake_cross_file.txt')
        self.meson_crossfile = self._gen_crossfile('meson_cross_file.txt')

    def __getattr__(self, name):
        return getattr(self.options, name)

    def _is_debianlike(self):
        return os.path.isfile('/etc/debian_version')

    def _detect_libdir(self):
        if self._is_debianlike():
            try:
                pc = subprocess.Popen(['dpkg-architecture', '-qDEB_HOST_MULTIARCH'],
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL)
                (stdo, _) = pc.communicate()
                if pc.returncode == 0:
                    archpath = stdo.decode().strip()
                    return 'lib/' + archpath
            except Exception:
                pass
        if os.path.isdir('/usr/lib64') and not os.path.islink('/usr/lib64'):
            return 'lib64'
        return 'lib'

    def _detect_ninja(self):
        for n in ['ninja', 'ninja-build']:
            try:
                retcode = subprocess.check_call([n, '--version'],
                                                stdout=subprocess.DEVNULL)
            except (FileNotFoundError, PermissionError):
                # Doesn't exist in PATH or isn't executable
                continue
            if retcode == 0:
                return n

    def _detect_meson(self):
        for n in ['meson.py', 'meson']:
            try:
                retcode = subprocess.check_call([n, '--version'],
                                                stdout=subprocess.DEVNULL)
            except (FileNotFoundError, PermissionError):
                # Doesn't exist in PATH or isn't executable
                continue
            if retcode == 0:
                return n

    @property
    def configure_option(self):
        configure_options = [tlc.configure_option for tlc in self.toolchains]
        return " ".join(configure_options)

    @property
    def cmake_option(self):
        cmake_options = [tlc.cmake_option for tlc in self.toolchains]
        return " ".join(cmake_options)

    def _set_env(self, env, cross_compile_env, cross_compile_path):
        if env is None:
            env = Defaultdict(str, os.environ)

        bin_dirs = []
        if cross_compile_env:
            for k, v in self.cross_env.get('env', {}).items():
                if k.startswith('_format_'):
                    v = v.format(**self.cross_env)
                    k = k[8:]
                env[k] = v
            for toolchain in self.toolchains:
                toolchain.set_env(env)
        if cross_compile_path:
            for tlc in self.toolchains:
                bin_dirs += tlc.get_bin_dir()

        pkgconfig_path = pj(self.install_dir, self.libprefix, 'pkgconfig')
        env['PKG_CONFIG_PATH'] = ':'.join([env['PKG_CONFIG_PATH'], pkgconfig_path])

        # Add ccache path
        for p in ('/usr/lib/ccache', '/usr/lib64/ccache'):
            if os.path.isdir(p):
                ccache_path = [p]
                break
        else:
            ccache_path = []
        env['PATH'] = ':'.join(bin_dirs +
                               [pj(self.install_dir, 'bin')] +
                               ccache_path +
                               [env['PATH']])

        env['LD_LIBRARY_PATH'] = ':'.join([env['LD_LIBRARY_PATH'],
                                          pj(self.install_dir, 'lib'),
                                          pj(self.install_dir, 'lib64')
                                          ])

        env['CPPFLAGS'] = " ".join(['-I'+pj(self.install_dir, 'include'), env['CPPFLAGS']])
        env['LDFLAGS'] = " ".join(['-L'+pj(self.install_dir, 'lib'), env['LDFLAGS']])
        return env

    def run_command(self, command, cwd, context, env=None, input=None, cross_path_only=False):
        os.makedirs(cwd, exist_ok=True)
        cross_compile_env = True
        cross_compile_path = True
        if context.force_native_build:
            cross_compile_env = False
            cross_compile_path = False
        if cross_path_only:
            cross_compile_env = False
        env = self._set_env(env, cross_compile_env, cross_compile_path)
        log = None
        try:
            if not self.options.verbose:
                log = open(context.log_file, 'w')
            print("run command '{}'".format(command), file=log)
            print("env is :", file=log)
            for k, v in env.items():
                print("  {} : {!r}".format(k, v), file=log)

            kwargs = dict()
            if input:
                kwargs['stdin'] = input
            return subprocess.check_call(command, shell=True, cwd=cwd, env=env, stdout=log or sys.stdout, stderr=subprocess.STDOUT, **kwargs)
        finally:
            if log:
                log.close()

    def download(self, what, where=None):
        where = where or self.archive_dir
        file_path = pj(where, what.name)
        file_url = what.url or (REMOTE_PREFIX + what.name)
        if os.path.exists(file_path):
            if what.sha256 == get_sha256(file_path):
                raise SkipCommand()
            os.remove(file_path)
        urllib.request.urlretrieve(file_url, file_path)
        if not what.sha256:
            print('Sha256 for {} not set, do no verify download'.format(what.name))
        elif what.sha256 != get_sha256(file_path):
            os.remove(file_path)
            raise StopBuild()

    def install_packages(self):
        autoskip_file = pj(self.build_dir, ".install_packages_ok")
        if self.distname in ('fedora', 'redhat', 'centos'):
            package_installer = 'sudo dnf install {}'
            package_checker = 'rpm -q --quiet {}'
        elif self.distname in ('debian', 'Ubuntu'):
            package_installer = 'sudo apt-get install {}'
            package_checker = 'LANG=C dpkg -s {} 2>&1 | grep Status | grep "ok installed" 1>/dev/null 2>&1'
        mapper_name = "{host}_{target}_{build_type}".format(
            host=self.distname,
            target=self.build_target,
            build_type='static' if self.options.build_static else 'dyn')
        try:
            package_name_mapper = PACKAGE_NAME_MAPPERS[mapper_name]
        except KeyError:
            print("SKIP : We don't know which packages we must install to compile"
                  " a {target} {build_type} version on a {host} host.".format(
                      target=self.build_target,
                      build_type='static' if self.options.build_static else 'dyn',
                      host=self.distname))
            return

        packages_list = package_name_mapper.get('COMMON', [])
        for dep in self.targetsDict.values():
            packages = package_name_mapper.get(dep.name)
            if packages:
                packages_list += packages
                dep.skip = True
        if os.path.exists(autoskip_file):
            print("SKIP")
            return

        packages_to_install = []
        for package in packages_list:
            print(" - {} : ".format(package), end="")
            command = package_checker.format(package)
            try:
                subprocess.check_call(command, shell=True)
            except subprocess.CalledProcessError:
                print("NEEDED")
                packages_to_install.append(package)
            else:
                print("SKIP")

        if packages_to_install:
            command = package_installer.format(" ".join(packages_to_install))
            print(command)
            subprocess.check_call(command, shell=True)
        else:
            print("SKIP, No package to install.")

        with open(autoskip_file, 'w'):
            pass

class _MetaToolchain(type):
    def __new__(cls, name, bases, dct):
        _class = type.__new__(cls, name, bases, dct)
        if name != 'Toolchain':
            Toolchain.all_toolchains[name] = _class
        return _class


class Toolchain(metaclass=_MetaToolchain):
    all_toolchains = {}
    configure_option = ""
    cmake_option = ""

    def __init__(self, buildEnv):
        self.buildEnv = buildEnv

    @property
    def full_name(self):
        return "{name}-{version}".format(
            name = self.name,
            version = self.version)

    def set_env(self, env):
        pass


class mingw32_toolchain(Toolchain):
    name = 'mingw32'
    arch_full = 'i686-w64-mingw32'

    @property
    def root_path(self):
        return self.buildEnv.cross_env['root_path']

    @property
    def binaries(self):
        return {k:which('{}-{}'.format(self.arch_full, v))
                for k, v in (('CC', 'gcc'),
                             ('CXX', 'g++'),
                             ('AR', 'ar'),
                             ('STRIP', 'strip'),
                             ('WINDRES', 'windres'),
                             ('RANLIB', 'ranlib'))
               }

    @property
    def configure_option(self):
        return '--host={}'.format(self.arch_full)

    def get_bin_dir(self):
        return [pj(self.root_path, 'bin')]

    def set_env(self, env):
        for k, v in self.binaries.items():
            env[k] = v

        env['PKG_CONFIG_LIBDIR'] = pj(self.root_path, 'lib', 'pkgconfig')
        env['CFLAGS'] = " -O2 -g -pipe -Wall -Wp,-D_FORTIFY_SOURCE=2 -fexceptions --param=ssp-buffer-size=4 "+env['CFLAGS']
        env['CXXFLAGS'] =" -O2 -g -pipe -Wall -Wp,-D_FORTIFY_SOURCE=2 -fexceptions --param=ssp-buffer-size=4 "+env['CXXFLAGS']


class Builder:
    def __init__(self, options, targetDef='KiwixTools'):
        self.targets = OrderedDict()
        self.buildEnv = buildEnv = BuildEnv(options, self.targets)

        _targets = {}
        self.add_targets(targetDef, _targets)
        dependencies = self.order_dependencies(_targets, targetDef)
        dependencies = list(remove_duplicates(dependencies))

        for dep in dependencies:
            self.targets[dep] = _targets[dep]

    def add_targets(self, targetName, targets):
        if targetName in targets:
            return
        targetClass = Dependency.all_deps[targetName]
        target = targetClass(self.buildEnv)
        targets[targetName] = target
        for dep in target.dependencies:
            self.add_targets(dep, targets)

    def order_dependencies(self, _targets, targetName):
        target = _targets[targetName]
        for depName in target.dependencies:
            yield from self.order_dependencies(_targets, depName)
        yield targetName

    def prepare_sources(self):
        toolchain_sources = (tlc.source for tlc in self.buildEnv.toolchains if tlc.source)
        for toolchain_source in toolchain_sources:
            print("prepare sources for toolchain {} :".format(toolchain_source.name))
            toolchain_source.prepare()

        sources = (dep.source for dep in self.targets.values() if not dep.skip)
        sources = remove_duplicates(sources, lambda s: s.__class__)
        for source in sources:
            print("prepare sources {} :".format(source.name))
            source.prepare()

    def build(self):
        builders = (dep.builder for dep in self.targets.values() if not dep.skip)
        for builder in builders:
            print("build {} :".format(builder.name))
            builder.build()

    def run(self):
        try:
            print("[INSTALL PACKAGES]")
            self.buildEnv.install_packages()
            self.buildEnv.finalize_setup()
            print("[PREPARE]")
            self.prepare_sources()
            print("[BUILD]")
            self.build()
        except StopBuild:
            sys.exit("Stopping build due to errors")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('working_dir', default=".", nargs='?')
    parser.add_argument('--libprefix', default=None)
    parser.add_argument('--build-static', action="store_true")
    parser.add_argument('--build-target', default="native", choices=BuildEnv.build_targets)
    parser.add_argument('--verbose', '-v', action="store_true",
                        help=("Print all logs on stdout instead of in specific"
                              " log files per commands"))
    return parser.parse_args()


if __name__ == "__main__":
    options = parse_args()
    options.working_dir = os.path.abspath(options.working_dir)
    builder = Builder(options)
    builder.run()
