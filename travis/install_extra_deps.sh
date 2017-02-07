#!/usr/bin/env bash

orig_dir=$(pwd)

sudo apt-get update -qq
sudo apt-get install -qq uuid-dev libicu-dev libctpp2-dev automake libtool python3-pip zlib1g-dev lzma-dev libbz2-dev cmake
pip3 install meson

# ninja
git clone git://github.com/ninja-build/ninja.git
cd ninja
git checkout release
./configure.py --bootstrap
sudo cp ninja /bin

cd $orig_dir

git clone https://github.com/kiwix/kiwix-build
