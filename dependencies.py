import shutil

from dependency_utils import (
    Dependency,
    ReleaseDownload,
    GitClone,
    MakeBuilder,
    CMakeBuilder,
    MesonBuilder)

from utils import Remotefile, pj, SkipCommand

# *************************************
# Missing dependencies
# Is this ok to assume that those libs
# exist in your "distri" (linux/mac) ?
# If not, we need to compile them here
# *************************************
# Zlib
# LZMA
# aria2
# Argtable
# MSVirtual
# Android
# libiconv
# gettext
# *************************************


class zlib(Dependency):
    name = 'zlib'
    version = '1.2.8'

    class Source(ReleaseDownload):
        archive = Remotefile('zlib-1.2.8.tar.gz',
                             '36658cb768a54c1d4dec43c3116c27ed893e88b02ecfcb44f2166f9c0b7f2a0d')
        patches = ['zlib_std_libname.patch']

    class Builder(CMakeBuilder):
        @property
        def configure_option(self):
            return "-DINSTALL_PKGCONFIG_DIR={}".format(pj(self.buildEnv.install_dir, self.buildEnv.libprefix, 'pkgconfig'))


class UUID(Dependency):
    name = 'uuid'
    version = "1.43.4"

    class Source(ReleaseDownload):
        archive = Remotefile('e2fsprogs-libs-1.43.4.tar.gz',
                             'eed4516325768255c9745e7b82c9d7d0393abce302520a5b2cde693204b0e419',
                             'https://www.kernel.org/pub/linux/kernel/people/tytso/e2fsprogs/v1.43.4/e2fsprogs-libs-1.43.4.tar.gz')
        extract_dir = 'e2fsprogs-libs-1.43.4'

    class Builder(MakeBuilder):
        configure_option = "--enable-libuuid"
        configure_env = {'_format_CFLAGS': "{env.CFLAGS} -fPIC"}
        make_target = 'libs'
        make_install_target = 'install-libs'


class Xapian(Dependency):
    name = "xapian-core"
    version = "1.4.0"

    class Source(ReleaseDownload):
        archive = Remotefile('xapian-core-1.4.0.tar.xz',
                             '10584f57112aa5e9c0e8a89e251aecbf7c582097638bfee79c1fe39a8b6a6477')
        patches = ["xapian_pkgconfig.patch",
                   "xapian_no_hardcode_lz.patch"]

    class Builder(MakeBuilder):
        configure_option = "--disable-sse --disable-backend-inmemory --disable-documentation"
        dynamic_configure_option = "--enable-shared --disable-static"
        static_configure_option = "--enable-static --disable-shared"
        configure_env = {'_format_LDFLAGS': "-L{buildEnv.install_dir}/{buildEnv.libprefix}",
                         '_format_CXXFLAGS': "-I{buildEnv.install_dir}/include"}

    @property
    def dependencies(self):
        deps = ['zlib']
        if self.buildEnv.build_target == 'win32':
            return deps
        return deps + ['UUID']


class CTPP2(Dependency):
    name = "ctpp2"
    version = "2.8.3"

    class Source(ReleaseDownload):
        archive = Remotefile('ctpp2-2.8.3.tar.gz',
                             'a83ffd07817adb575295ef40fbf759892512e5a63059c520f9062d9ab8fb42fc')
        patches = ["ctpp2_include.patch",
                   "ctpp2_no_src_modification.patch",
                   "ctpp2_fix-static-libname.patch",
                   "ctpp2_mingw32.patch",
                   "ctpp2_dll_export_VMExecutable.patch",
                   "ctpp2_win_install_lib_in_lib_dir.patch",
                   "ctpp2_iconv_support.patch"]

    class Builder(CMakeBuilder):
        configure_option = "-DMD5_SUPPORT=OFF"


class Pugixml(Dependency):
    name = "pugixml"
    version = "1.2"

    class Source(ReleaseDownload):
        archive = Remotefile('pugixml-1.2.tar.gz',
                             '0f422dad86da0a2e56a37fb2a88376aae6e931f22cc8b956978460c9db06136b')
        patches = ["pugixml_meson.patch"]

    Builder = MesonBuilder


class MicroHttpd(Dependency):
    name = "libmicrohttpd"
    version = "0.9.46"

    class Source(ReleaseDownload):
        archive = Remotefile('libmicrohttpd-0.9.46.tar.gz',
                             '06dbd2654f390fa1e8196fe063fc1449a6c2ed65a38199a49bf29ad8a93b8979',
                             'http://ftp.gnu.org/gnu/libmicrohttpd/libmicrohttpd-0.9.46.tar.gz')

    class Builder(MakeBuilder):
        configure_option = "--disable-https --without-libgcrypt --without-libcurl"
        dynamic_configure_option = "--enable-shared --disable-static"
        static_configure_option = "--enable-static --disable-shared"


class Icu(Dependency):
    name = "icu4c"
    version = "56_1"

    class Source(ReleaseDownload):
        archive = Remotefile('icu4c-56_1-src.tgz',
                             '3a64e9105c734dcf631c0b3ed60404531bce6c0f5a64bfe1a6402a4cc2314816')
        patches = ["icu4c_fix_static_lib_name_mingw.patch"]
        data = Remotefile('icudt56l.dat',
                          'e23d85eee008f335fc49e8ef37b1bc2b222db105476111e3d16f0007d371cbca')

        def _download_data(self, context):
            self.buildEnv.download(self.data)

        def _copy_data(self, context):
            context.try_skip(self.extract_path)
            shutil.copyfile(pj(self.buildEnv.archive_dir, self.data.name), pj(self.extract_path, 'source', 'data', 'in', self.data.name))

        def prepare(self):
            super().prepare()
            self.command("download_data", self._download_data)
            self.command("copy_data", self._copy_data)

    class Builder(MakeBuilder):
        subsource_dir = "source"
        configure_option = "--disable-samples --disable-tests --disable-extras --disable-dyload"
        dynamic_configure_option = "--enable-shared --disable-static"
        static_configure_option = "--enable-static --disable-shared"


class Icu_native(Icu):
    force_native_build = True

    class Builder(Icu.Builder):
        @property
        def build_path(self):
            return super().build_path+"_native"

        def _install(self, context):
            raise SkipCommand()


class Icu_cross_compile(Icu):
    dependencies = ['Icu_native']

    class Builder(Icu.Builder):
        @property
        def configure_option(self):
            Icu_native = self.buildEnv.targetsDict['Icu_native']
            return super().configure_option + " --with-cross-build=" + Icu_native.builder.build_path


class Zimlib(Dependency):
    name = "zimlib"

    class Source(GitClone):
        #git_remote = "https://gerrit.wikimedia.org/r/p/openzim.git"
        git_remote = "https://github.com/mgautierfr/openzim"
        git_dir = "openzim"
        git_ref = "meson"

    class Builder(MesonBuilder):
        subsource_dir = "zimlib"


class Kiwixlib(Dependency):
    name = "kiwix-lib"
    dependencies = ['zlib']

    @property
    def dependencies(self):
        if self.buildEnv.build_target == 'win32':
            return ["Xapian", "CTPP2", "Pugixml", "Icu_cross_compile", "Zimlib"]
        return ["Xapian", "CTPP2", "Pugixml", "Icu", "Zimlib"]

    class Source(GitClone):
        git_remote = "https://github.com/kiwix/kiwix-lib.git"
        git_dir = "kiwix-lib"

    class Builder(MesonBuilder):
        configure_option = "-Dctpp2-install-prefix={buildEnv.install_dir}"


class KiwixTools(Dependency):
    name = "kiwix-tools"
    dependencies = ["Kiwixlib", "MicroHttpd", "zlib"]

    class Source(GitClone):
        git_remote = "https://github.com/kiwix/kiwix-tools.git"
        git_dir = "kiwix-tools"

    class Builder(MesonBuilder):
        @property
        def configure_option(self):
            base_options = "-Dctpp2-install-prefix={buildEnv.install_dir}"
            if self.buildEnv.build_static:
                base_options += " -Dstatic-linkage=true"
            return base_options
