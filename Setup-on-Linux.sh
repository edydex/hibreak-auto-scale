#!/bin/sh
set -eu
HIBREAK_SETUP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /bin/bash "$HIBREAK_SETUP_DIR/bootstrap_unix.sh" "$@"
