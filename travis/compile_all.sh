#!/usr/bin/env bash

set -e

if [ "${STATIC_BUILD}" = "true" ]; then
    OPTION="${BUILD_TARGET}_static"
else
    OPTION="${BUILD_TARGET}_dyn"
fi

./kiwix-build.py --build-target=${OPTION}
