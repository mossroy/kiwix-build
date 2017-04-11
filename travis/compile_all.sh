#!/usr/bin/env bash

set -e

BASE_DIR="BUILD_${PLATFORM}"
DEPS_ARCHIVES_DIR=${HOME}/DEPS_ARCHIVES
mkdir -p ${DEPS_ARCHIVES_DIR}
NIGHTLY_ARCHIVES_DIR=${HOME}/NIGHTLY_ARCHIVES
mkdir -p ${NIGHTLY_ARCHIVES_DIR}

cd ${HOME}

if [[ "$TRAVIS_EVENT_TYPE" = "cron" ]]
then
  if [[ ${PLATFORM} = android* ]]
  then
    TARGETS="libzim kiwix-lib"
  else
    TARGETS="libzim kiwix-lib kiwix-tools"
  fi

  for TARGET in ${TARGETS}
  do
    echo $TARGET
    ${TRAVIS_BUILD_DIR}/kiwix-build.py \
      --target-platform $PLATFORM \
      --build-deps-only \
      ${TARGET}
    rm ${BASE_DIR}/.install_packages_ok

    (
      cd ${BASE_DIR}
      if [ -f meson_cross_file.txt ]
      then
        MESON_FILE=meson_cross_file.txt
      fi
      ANDROID_NDK_DIR=$(find . -name "android-ndk*")
      tar -czf "${DEPS_ARCHIVES_DIR}/deps_${PLATFORM}_${TARGET}.tar.gz" INSTALL ${MESON_FILE} ${ANDROID_NDK_DIR}
    )

    ${TRAVIS_BUILD_DIR}/kiwix-build.py --target-platform $PLATFORM ${TARGET}
    rm ${BASE_DIR}/.install_packages_ok
  done

  # We have build every thing. Now create archives for public deployement.
  case ${PLATFORM} in
    native_static)
      ARCHIVE_NAME="kiwix-tools_linux64_$(date +%Y-%m-%d).tar.gz"
      FILES_LIST="kiwix-install kiwix-manage kiwix-read kiwix-search kiwix-serve"
      (
        cd ${BASE_DIR}/INSTALL/bin
        tar -czf "${NIGHTLY_ARCHIVES_DIR}/$ARCHIVE_NAME" $FILES_LIST
      )
      ;;
    win32_static)
      ARCHIVE_NAME="kiwix-tools_win32_$(date +%Y-%m-%d).tar.gz"
      FILES_LIST="kiwix-install.exe kiwix-manage.exe kiwix-read.exe kiwix-search.exe kiwix-serve.exe"
      (
        cd ${BASE_DIR}/INSTALL/bin
        tar -czf "${NIGHTLY_ARCHIVES_DIR}/$ARCHIVE_NAME" $FILES_LIST
      )
      ;;
  esac

else
  # No a cron job, we just have to build to be sure nothing is broken.
  if [[ ${PLATFORM} = android* ]]
  then
    TARGET=kiwix-lib
  else
    TARGET=kiwix-tools
  fi
  ${TRAVIS_BUILD_DIR}/kiwix-build.py \
    --target-platform $PLATFORM \
    ${TARGET}
fi
