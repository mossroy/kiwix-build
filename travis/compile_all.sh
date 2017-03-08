#!/usr/bin/env bash

set -e

if [[ "x$ANDROID_BUILD" == "x" ]]
then
    ./kiwix-build.py $BUILD_OPTION
else
    ./kiwix-build-apk.py
fi
