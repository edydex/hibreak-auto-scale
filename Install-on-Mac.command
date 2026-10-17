#!/bin/sh
set -eu
HIBREAK_INSTALLER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export HIBREAK_PAUSE_ON_EXIT=1
exec /bin/bash "$HIBREAK_INSTALLER_DIR/bootstrap_unix.sh" -- --install-only "$@"
