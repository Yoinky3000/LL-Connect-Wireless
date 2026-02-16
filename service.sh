#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source $ROOT_DIR/vars.sh "$@"

DEV=1 ./venv/bin/python $ROOT_DIR/src/service.py $1