#!/usr/bin/env python3

import os, sys, shutil
import argparse
import urllib.request
import subprocess
import platform
from collections import OrderedDict

from dependencies import Dependency
from dependency_utils import ReleaseDownload, Builder
from utils import (
    pj,
    remove_duplicates,
    add_execution_right,
    get_sha256,
    StopBuild,
    SkipCommand,
    Defaultdict,
    Remotefile,
    Context)


SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

class BuildEnv:
    def __init__(self, options, targetsDict):
        self.source_dir = pj(options.working_dir, "SOURCE")
        build_dir = "BUILD_android_apk"
        self.build_dir = pj(options.working_dir, build_dir)
        self.archive_dir = pj(options.working_dir, "ARCHIVE")
        self.toolchain_dir = pj(options.working_dir, "TOOLCHAINS")
        self.log_dir = pj(self.build_dir, 'LOGS')
        self.install_dir = pj(self.build_dir, "INSTALL")
        for d in (self.source_dir,
                  self.build_dir,
                  self.archive_dir,
                  self.toolchain_dir,
                  self.log_dir,
                  self.install_dir):
            os.makedirs(d, exist_ok=True)
        self.detect_platform()
        self.setup_toolchains()
        self.options = options
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

    def setup_toolchains(self):
        toolchain_names = ['android_sdk']
        self.toolchains =[Toolchain.all_toolchains[toolchain_name](self)
                              for toolchain_name in toolchain_names]

    def __getattr__(self, name):
        return getattr(self.options, name)

    def _set_env(self, env, cross_compile_env, cross_compile_path):
        if env is None:
            env = Defaultdict(str, os.environ)

        env['PATH'] = ':'.join([pj(self.install_dir, 'bin')] + [env['PATH']])

        for toolchain in self.toolchains:
            toolchain.set_env(env)

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
                kwargs['stdin'] = subprocess.PIPE
            process = subprocess.Popen(command, shell=True, cwd=cwd, env=env, stdout=log or sys.stdout, stderr=subprocess.STDOUT, **kwargs)
            if input:
                process.communicate(input.encode())
            retcode = process.wait()
            if retcode:
                raise subprocess.CalledProcessError(retcode, command)
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
            print('Invalid sha ({}) for {}.\nIntended {}'.format(
                get_sha256(file_path),
                file_path,
                what.sha256))
            raise StopBuild()

    def install_packages(self):
        autoskip_file = pj(self.build_dir, ".install_packages_ok")
        if self.distname in ('fedora', 'redhat', 'centos'):
            package_installer = 'sudo dnf install {}'
            package_checker = 'rpm -q --quiet {}'
        elif self.distname in ('debian', 'Ubuntu'):
            package_installer = 'sudo apt-get install {}'
            package_checker = 'LANG=C dpkg -s {} 2>&1 | grep Status | grep "ok installed" 1>/dev/null 2>&1'
        mapper_name = "{host}_{target}".format(
            host=self.distname,
            target=self.platform_info)
        try:
            package_name_mapper = PACKAGE_NAME_MAPPERS[mapper_name]
        except KeyError:
            print("SKIP : We don't know which packages we must install to compile"
                  " a {target} {build_type} version on a {host} host.".format(
                      target=self.platform_info,
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
    Builder = None
    Source = None

    def __init__(self, buildEnv):
        self.buildEnv = buildEnv
        self.source = self.Source(self) if self.Source else None
        self.builder = self.Builder(self) if self.Builder else None

    @property
    def full_name(self):
        return "{name}-{version}".format(
            name = self.name,
            version = self.version)

    @property
    def source_path(self):
        return pj(self.buildEnv.source_dir, self.source.source_dir)

    @property
    def _log_dir(self):
        return self.buildEnv.log_dir

    def set_env(self, env):
        pass

    def command(self, name, function, *args):
        print("  {} {} : ".format(name, self.name), end="", flush=True)
        log = pj(self._log_dir, 'cmd_{}_{}.log'.format(name, self.name))
        context = Context(name, log, True)
        try:
            ret = function(*args, context=context)
            context._finalise()
            print("OK")
            return ret
        except SkipCommand:
            print("SKIP")
        except subprocess.CalledProcessError:
            print("ERROR")
            try:
                with open(log, 'r') as f:
                    print(f.read())
            except:
                pass
            raise StopBuild()
        except:
            print("ERROR")
            raise

class android_sdk(Toolchain):
    name = 'android-sdk'
    version = 'r25.2.3'

    class Source(ReleaseDownload):
        archive = Remotefile('tools_r25.2.3-linux.zip',
                             '1b35bcb94e9a686dff6460c8bca903aa0281c6696001067f34ec00093145b560',
                             'https://dl.google.com/android/repository/tools_r25.2.3-linux.zip')

    class Builder(Builder):

        @property
        def install_path(self):
            return pj(self.buildEnv.toolchain_dir, self.target.full_name)

        def _build_platform(self, context):
            context.try_skip(self.install_path)
            tools_dir = pj(self.install_path, 'tools')
            shutil.copytree(self.source_path, tools_dir)
            script = pj(tools_dir, 'android')
            command = '{script} --verbose update sdk -a --no-ui --filter {packages}'
            command = command.format(
                script=script,
                packages = ','.join(str(i) for i in [1,2,8,34,162])
            )
            # packages correspond to :
            # - 1 : Android SDK Tools, revision 25.2.5
            # - 2 : Android SDK Platform-tools, revision 25.0.3
            # - 8 : Android SDK Build-tools, revision 24.0.1
            # - 34 : SDK Platform Android 7.0, API 24, revision 2
            # - 162 : Android Support Repository, revision 44
            self.buildEnv.run_command(command, self.install_path, context, input="y\n")

        def _fix_licenses(self, context):
            context.try_skip(self.install_path)
            os.makedirs(pj(self.install_path, 'licenses'), exist_ok=True)
            with open(pj(self.install_path, 'licenses', 'android-sdk-license'), 'w') as f:
                f.write("\n8933bad161af4178b1185d1a37fbf41ea5269c55")

        def build(self):
            self.command('build_platform', self._build_platform)
            self.command('fix_licenses', self._fix_licenses)

    def get_bin_dir(self):
        return []

    def set_env(self, env):
        env['ANDROID_HOME'] = self.builder.install_path


class Builder:
    def __init__(self, options):
        self.targets = OrderedDict()
        self.buildEnv = buildEnv = BuildEnv(options, self.targets)

        _targets = {}
        targetDef = 'KiwixAndroid'
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
        toolchain_builders = (tlc.builder for tlc in self.buildEnv.toolchains if tlc.builder)
        for toolchain_builder in toolchain_builders:
            print("build toolchain {} :".format(toolchain_builder.name))
            toolchain_builder.build()

        builders = (dep.builder for dep in self.targets.values() if (dep.builder and not dep.skip))
        for builder in builders:
            print("build {} :".format(builder.name))
            builder.build()

    def run(self):
        try:
            print("[INSTALL PACKAGES]")
            #self.buildEnv.install_packages()
            print("[PREPARE]")
            self.prepare_sources()
            print("[BUILD]")
            self.build()
        except StopBuild:
            sys.exit("Stopping build due to errors")


def build_android_lib(options, platform):
    kiwix_build_script = pj(SCRIPT_DIR, 'kiwix-build.py')
    command = "{script} --working-dir {working_dir} --target-platform {platform} --clean-at-end Kiwixlib"
    command = command.format(
        script = kiwix_build_script,
        working_dir = options.working_dir,
        platform = "android_{}".format(platform)
    )
    subprocess.check_call(command, shell=True)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--working-dir', default=".")
    parser.add_argument('--verbose', '-v', action="store_true",
                        help=("Print all logs on stdout instead of in specific"
                              " log files per commands"))
    return parser.parse_args()


if __name__ == "__main__":
    options = parse_args()
    options.working_dir = os.path.abspath(options.working_dir)
    for _platform in ['arm', 'arm64', 'mips', 'mips64', 'x86', 'x86_64']:
        print("------- BUILDING Kiwixlib for android {} -------".format(
            _platform))
        build_android_lib(options, _platform)

    print("--------------- BUILDING Kiwix apk -------------------------")
    builder = Builder(options)
    builder.run()
