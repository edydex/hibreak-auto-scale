#!/usr/bin/env bash
# Exercise the actual downloads/extraction/version checks. No ADB server/device
# command is run. CI starts with a new private runtime folder on each OS.
set -euo pipefail
ci_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -z "${HIBREAK_RUNTIME_DIR:-}" ]; then
    printf '%s\n' 'Set HIBREAK_RUNTIME_DIR to a new temporary runtime folder.' >&2
    exit 1
fi
if [ -e "$HIBREAK_RUNTIME_DIR" ]; then
    printf '%s\n' 'Fresh-runtime check requires a previously absent runtime folder.' >&2
    exit 1
fi
export HIBREAK_BOOTSTRAP_SOURCE_ONLY=1
source "$ci_root/bootstrap_unix.sh"
# Force the missing-dependency branch, even on tool-rich CI runners. The actual
# pinned archive verification/extraction and installed version checks are used.
hb_existing_python() { return 1; }
hb_existing_adb() { return 1; }
hb_main --check-dependencies --accept-tool-licenses
