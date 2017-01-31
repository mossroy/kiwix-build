#!/usr/bin/env bash

OPTION=""
if [ "${STATIC_BUILD}" = "true" ]; then
    OPTION="--build-static"
fi

STATIC_BUILD


./kiwix-build.py ${OPTION}
