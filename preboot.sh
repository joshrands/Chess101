#!/bin/bash

dir=$(dirname $0)
cd $dir
git stash
git pull
./boot.sh
