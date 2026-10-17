#!/bin/bash
# Bash 3.2-compatible dependency bootstrap. No Homebrew, pip, Xcode, sudo,
# shell-profile changes, system installation, or Gatekeeper bypass is used.
set -eu
umask 077

HIBREAK_BOOTSTRAP_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HIBREAK_PYTHON_RELEASE=20261013
HIBREAK_PYTHON_VERSION=3.12.15
HIBREAK_ADB_VERSION=37.0.1
HIBREAK_STAGE=
HIBREAK_LOCK_KIND=
HIBREAK_LOG=

hb_say() {
    printf '%s\n' "$*"
    if [ -n "$HIBREAK_LOG" ]; then printf '%s\n' "$*" >> "$HIBREAK_LOG"; fi
}

hb_fail() { hb_say "Setup stopped: $*" >&2; return 1; }

hb_sha256() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
    else hb_fail 'This computer needs a SHA256 tool (shasum or sha256sum).'; fi
}

hb_platform() {
    HIBREAK_SYSTEM=$(uname -s)
    HIBREAK_ARCH=$(uname -m)
    case "$HIBREAK_SYSTEM" in
        Darwin)
            HIBREAK_PLATFORM=macos
            # Prefer native Apple Silicon even when Terminal was started in Rosetta.
            if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || true)" = 1 ]; then HIBREAK_ARCH=arm64; fi
            case "$HIBREAK_ARCH" in arm64|x86_64) ;; *) hb_fail 'This Mac CPU is unsupported.'; return 1;; esac
            local major
            major=$(/usr/bin/sw_vers -productVersion | cut -d. -f1)
            case "$major" in ''|*[!0-9]*) hb_fail 'Cannot identify this macOS version.'; return 1;; esac
            [ "$major" -ge 11 ] || { hb_fail 'The automatic runtime setup requires macOS 11 or newer.'; return 1; }
            HIBREAK_CACHE=${HIBREAK_RUNTIME_DIR:-"$HOME/Library/Application Support/HiBreak Auto Scale/runtime"}
            ;;
        Linux)
            HIBREAK_PLATFORM=linux
            case "$HIBREAK_ARCH" in arm64) HIBREAK_ARCH=aarch64;; x86_64|aarch64) ;; *) hb_fail 'Linux supports x86_64 or aarch64 CPUs only.'; return 1;; esac
            HIBREAK_CACHE=${HIBREAK_RUNTIME_DIR:-"${XDG_CACHE_HOME:-$HOME/.cache}/hibreak-auto-scale/runtime"}
            ;;
        *) hb_fail 'Use the Windows launcher on Windows. This launcher supports macOS and Linux.'; return 1;;
    esac
    case "$HIBREAK_CACHE" in /*) ;; *) hb_fail 'Runtime folder must be an absolute path.'; return 1;; esac
    [ -n "${HOME:-}" ] || { hb_fail 'Your user home folder could not be identified.'; return 1; }
}

hb_select_pins() {
    case "$HIBREAK_PLATFORM-$HIBREAK_ARCH" in
        macos-arm64)
            HIBREAK_PYTHON_TARGET=aarch64-apple-darwin
            HIBREAK_PYTHON_SHA=9866e11cf2ae9caa1e671383786f248859a52dd8bfb702fb4c0dc2c65f1d36de;;
        macos-x86_64)
            HIBREAK_PYTHON_TARGET=x86_64-apple-darwin
            HIBREAK_PYTHON_SHA=d09998f85752b646873a8a6bc7eea442a0d251b1c8d2413aa8ea06ef131c3335;;
        linux-x86_64)
            HIBREAK_PYTHON_TARGET=x86_64-unknown-linux-gnu
            HIBREAK_PYTHON_SHA=178d3d83b6e8e99285a65d3fce9c16b87952cc5efdb4d1a0e3ff3be18ff0fc9c;;
        linux-aarch64)
            HIBREAK_PYTHON_TARGET=aarch64-unknown-linux-gnu
            HIBREAK_PYTHON_SHA=9467a99bacc7d90b64b02de7fa9ecfc99b72905e64e74f7ff6b460ad95cfed5a;;
        *) hb_fail 'No verified Python runtime is available for this CPU.'; return 1;;
    esac
    HIBREAK_PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/$HIBREAK_PYTHON_RELEASE/cpython-$HIBREAK_PYTHON_VERSION%2B$HIBREAK_PYTHON_RELEASE-$HIBREAK_PYTHON_TARGET-install_only_stripped.tar.gz"
    case "$HIBREAK_PLATFORM-$HIBREAK_ARCH" in
        macos-*)
            HIBREAK_ADB_URL="https://dl.google.com/android/repository/platform-tools_r$HIBREAK_ADB_VERSION-darwin.zip"
            HIBREAK_ADB_SHA=ee39ad5967e95c2a07f04dbcbde96b1a0c916ba376096db5d2f498b7727a5d1d;;
        linux-x86_64)
            HIBREAK_ADB_URL="https://dl.google.com/android/repository/platform-tools_r$HIBREAK_ADB_VERSION-linux.zip"
            HIBREAK_ADB_SHA=d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1;;
        linux-aarch64) HIBREAK_ADB_URL=; HIBREAK_ADB_SHA=;;
    esac
}

hb_python_works() {
    [ -x "$1" ] || return 1
    # Apple's developer-tools stub can open an Xcode installation dialog.
    if [ "$1" = /usr/bin/python3 ] && [ "${HIBREAK_PLATFORM:-}" = macos ]; then
        local developer_dir
        developer_dir=$(/usr/bin/xcode-select -p 2>/dev/null || true)
        [ -n "$developer_dir" ] && [ -d "$developer_dir" ] || return 1
    fi
    "$1" -I -c 'import sys, argparse, ctypes, datetime, hashlib, json, pathlib, ssl, subprocess, zipfile, zlib; assert (3,10) <= sys.version_info[:2] < (4,0); assert json.loads("{\"text\":\"\u2713\"}")["text"] == "\u2713"' >/dev/null 2>&1
}

hb_adb_works() {
    [ -x "$1" ] || return 1
    local version_output
    version_output=$("$1" version 2>/dev/null) || return 1
    printf '%s\n' "$version_output" | awk '
        /^Android Debug Bridge version 1\.0\.41$/ { protocol=1 }
        /^Version [0-9]+\./ { split($2,v,"."); if (v[1]>=29) modern=1 }
        END { exit !(protocol && modern) }'
}

hb_existing_python() {
    local candidate
    [ "${HIBREAK_USE_PRIVATE_RUNTIME:-0}" != 1 ] || return 1
    for candidate in "$(command -v python3 2>/dev/null || true)" /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        if [ -n "$candidate" ] && hb_python_works "$candidate"; then HIBREAK_PYTHON=$candidate; return 0; fi
    done
    return 1
}

hb_existing_adb() {
    local candidate
    [ "${HIBREAK_USE_PRIVATE_RUNTIME:-0}" != 1 ] || return 1
    for candidate in "$(command -v adb 2>/dev/null || true)" /opt/homebrew/bin/adb "$HOME/Library/Android/sdk/platform-tools/adb" "$HOME/Android/Sdk/platform-tools/adb"; do
        if [ -n "$candidate" ] && hb_adb_works "$candidate"; then HIBREAK_ADB=$candidate; return 0; fi
    done
    return 1
}

hb_lock() {
    local attempts=0
    if [ "$HIBREAK_PLATFORM" = macos ]; then
        [ -x /usr/bin/shlock ] || { hb_fail 'The macOS lock tool is missing.'; return 1; }
        while ! /usr/bin/shlock -p "$$" -f "$HIBREAK_CACHE/.bootstrap.lock"; do
            attempts=$((attempts+1)); [ "$attempts" -le 45 ] || { hb_fail 'Another setup is still preparing downloads. Close it and try again.'; return 1; }
            [ "$attempts" -ne 1 ] || hb_say 'Waiting for the other setup to finish preparing its tools…'
            sleep 1
        done
        HIBREAK_LOCK_KIND=shlock
    else
        command -v flock >/dev/null 2>&1 || { hb_fail 'Linux needs the flock command from util-linux to prepare downloads safely.'; return 1; }
        exec 9> "$HIBREAK_CACHE/.bootstrap.lock"
        flock -w 45 9 || { hb_fail 'Another setup is still preparing downloads. Close it and try again.'; return 1; }
        HIBREAK_LOCK_KIND=flock
    fi
}

hb_unlock() {
    case "$HIBREAK_LOCK_KIND" in
        shlock) rm -f -- "$HIBREAK_CACHE/.bootstrap.lock";;
        flock) flock -u 9; exec 9>&-;;
    esac
    HIBREAK_LOCK_KIND=
}

hb_cleanup() {
    local status=$?
    trap - EXIT INT TERM
    [ -z "$HIBREAK_STAGE" ] || rm -rf -- "$HIBREAK_STAGE"
    hb_unlock
    if [ "$status" -ne 0 ] && [ -n "$HIBREAK_LOG" ]; then printf '\nSetup log: %s\n' "$HIBREAK_LOG" >&2; fi
    if [ "${HIBREAK_PAUSE_ON_EXIT:-0}" = 1 ] && [ -t 0 ]; then
        printf '\nPress Return to close this window. '
        read -r ignored || true
    fi
    exit "$status"
}

hb_fetch() {
    local url=$1 expected=$2 destination=$3 actual
    case "$url" in https://*) ;; *) hb_fail 'Downloads must use HTTPS.'; return 1;; esac
    command -v curl >/dev/null 2>&1 || { hb_fail 'This computer needs curl to download its tools.'; return 1; }
    if ! curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 20 --max-time 900 --retry 2 --silent --show-error "$url" -o "$destination" >> "$HIBREAK_LOG" 2>&1; then
        hb_fail 'The download did not finish. Check the internet connection and run setup again.'; return 1
    fi
    actual=$(hb_sha256 "$destination") || return 1
    [ "$actual" = "$expected" ] || { hb_fail 'A downloaded file failed its security checksum. Nothing from it was run or installed; retry with an unmodified kit.'; return 1; }
}

hb_validate_python_tar() {
    local archive=$1 list=$2 verbose=$3
    tar -tzf "$archive" > "$list" || return 1
    tar -tzvf "$archive" > "$verbose" || return 1
    awk -v platform="${HIBREAK_PLATFORM:-macos}" '
        { key=(platform=="macos" ? tolower($0) : $0); sub(/\/$/,"",key); if ($0 !~ /^python\// || $0 ~ /\\/ || $0 ~ /(^|\/)\.\.(\/|$)/ || $0 ~ /[[:space:][:cntrl:]]/ || seen[key]++) bad=1; count++ }
        END { exit (bad || count==0 || count>50000) }' "$list" || { hb_fail 'The Python archive contains an unsafe path.'; return 1; }
    awk '
        function safe(path, parts, stack, count, i, j, depth, walk) {
            count=split(path,parts,"/"); depth=0
            for (i=1;i<=count;i++) {
                if (parts[i]=="..") depth--
                else if (parts[i]!="" && parts[i]!=".") stack[++depth]=parts[i]
                if (depth<1) return 0
                walk=stack[1]; for (j=2;j<=depth;j++) walk=walk "/" stack[j]
                # A later path component must not traverse a symlink. This also
                # prevents parent components from escaping through link chains.
                if (i<count && (tolower(walk) in links)) return 0
            }
            return 1
        }
        NR==FNR {
            if ($0 ~ /^[^dl-]/) bad=1
            if ($0 ~ /^l/) {
                marker=index($0," -> "); if (!marker) { bad=1; next }
                name=substr($0,1,marker-1); sub(/^.* /,"",name)
                target=substr($0,marker+4)
                if (target ~ /^\// || target ~ /\\/ || target ~ /[[:space:]]/) { bad=1; next }
                links[tolower(name)]=1; sub(/[^\/]*$/,"",name)
                targets[++target_count]=name target
            }
            next
        }
        { if (!safe($0)) bad=1 }
        END { for (n=1;n<=target_count;n++) if (!safe(targets[n])) bad=1; exit bad }
        ' "$verbose" "$list" || { hb_fail 'The Python archive contains an unsafe link or special file.'; return 1; }
    grep -qx 'python/bin/python3.12' "$list" || { hb_fail 'The Python executable is missing from its archive.'; return 1; }
}

hb_require_glibc() {
    [ "$HIBREAK_PLATFORM" = linux ] || return 0
    local glibc
    glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null || true)
    printf '%s\n' "$glibc" | awk '$1=="glibc" { split($2,v,"."); if (v[1]>2 || (v[1]==2 && v[2]>=17)) good=1 } END {exit !good}' || {
        hb_fail 'Automatic Linux Python installation needs glibc 2.17 or newer. On Alpine/musl, install Python 3.10+ and ADB from your distribution, then rerun.'; return 1;
    }
}

hb_install_python() {
    local destination="$HIBREAK_CACHE/python-$HIBREAK_PYTHON_VERSION-$HIBREAK_PYTHON_RELEASE-$HIBREAK_PYTHON_TARGET"
    HIBREAK_PYTHON="$destination/python/bin/python3"
    if [ -f "$destination/.archive-sha256" ] && [ "$(cat "$destination/.archive-sha256")" = "$HIBREAK_PYTHON_SHA" ] && hb_python_works "$HIBREAK_PYTHON"; then return 0; fi
    hb_require_glibc || return 1
    hb_say "Preparing a private Python $HIBREAK_PYTHON_VERSION runtime (about 25–50 MB download)…"
    HIBREAK_STAGE=$(mktemp -d "$HIBREAK_CACHE/.stage-python.XXXXXXXX")
    hb_fetch "$HIBREAK_PYTHON_URL" "$HIBREAK_PYTHON_SHA" "$HIBREAK_STAGE/runtime.tar.gz" || return 1
    hb_validate_python_tar "$HIBREAK_STAGE/runtime.tar.gz" "$HIBREAK_STAGE/entries" "$HIBREAK_STAGE/verbose" || return 1
    mkdir "$HIBREAK_STAGE/install"
    tar -xzf "$HIBREAK_STAGE/runtime.tar.gz" -C "$HIBREAK_STAGE/install" >> "$HIBREAK_LOG" 2>&1 || { hb_fail 'Cannot unpack Python.'; return 1; }
    chmod -R go-rwx "$HIBREAK_STAGE/install"
    hb_python_works "$HIBREAK_STAGE/install/python/bin/python3" || { hb_fail 'The private Python runtime does not run on this computer. Its files remain uninstalled.'; return 1; }
    printf '%s\n' "$HIBREAK_PYTHON_SHA" > "$HIBREAK_STAGE/install/.archive-sha256"
    [ ! -e "$destination" ] || mv -- "$destination" "$destination.replaced-$(date +%Y%m%d%H%M%S)-$$"
    mv -- "$HIBREAK_STAGE/install" "$destination"
    rm -rf -- "$HIBREAK_STAGE"; HIBREAK_STAGE=
}

hb_accept_sdk_license() {
    local license="$HIBREAK_BOOTSTRAP_DIR/ANDROID-SDK-LICENSE.txt" digest answer
    [ -f "$license" ] || { hb_fail 'The Android SDK license is missing from this kit.'; return 1; }
    digest=$(hb_sha256 "$license") || return 1
    if [ -f "$HIBREAK_CACHE/android-sdk-license.accepted" ] && [ "$(cat "$HIBREAK_CACHE/android-sdk-license.accepted")" = "$digest" ]; then return 0; fi
    hb_say ''
    hb_say "ADB is Google's Android connection tool. Downloading it requires accepting the Android SDK license."
    hb_say "Full terms: $license"
    hb_say 'Official terms: https://developer.android.com/studio/terms'
    if [ "${HIBREAK_ACCEPT_TOOL_LICENSES:-0}" = 1 ]; then
        hb_say 'The --accept-tool-licenses option explicitly accepted these terms.'
        printf '%s\n' "$digest" > "$HIBREAK_CACHE/android-sdk-license.accepted"
        return 0
    fi
    printf 'Type agree to accept these terms and download ADB, or press Return to stop: '
    read -r answer || answer=
    case "$answer" in agree|AGREE) printf '%s\n' "$digest" > "$HIBREAK_CACHE/android-sdk-license.accepted";; *) hb_fail 'The Android SDK license was not accepted. No ADB download was started.'; return 1;; esac
}

hb_install_adb() {
    local destination="$HIBREAK_CACHE/platform-tools-$HIBREAK_ADB_VERSION-$HIBREAK_PLATFORM-$HIBREAK_ARCH"
    HIBREAK_ADB="$destination/platform-tools/adb"
    if [ -n "$HIBREAK_ADB_SHA" ] && [ -f "$destination/.archive-sha256" ] && [ "$(cat "$destination/.archive-sha256")" = "$HIBREAK_ADB_SHA" ] && hb_adb_works "$HIBREAK_ADB"; then return 0; fi
    if [ -z "$HIBREAK_ADB_URL" ]; then
        hb_fail 'Google does not provide a Linux ARM64 ADB archive. Install ADB 29+ using your Linux distribution (for example: sudo apt install adb), then run setup again.'; return 1
    fi
    hb_accept_sdk_license || return 1
    hb_say "Preparing Google's private ADB $HIBREAK_ADB_VERSION tools (about 10–17 MB download)…"
    HIBREAK_STAGE=$(mktemp -d "$HIBREAK_CACHE/.stage-adb.XXXXXXXX")
    hb_fetch "$HIBREAK_ADB_URL" "$HIBREAK_ADB_SHA" "$HIBREAK_STAGE/platform-tools.zip" || return 1
    mkdir "$HIBREAK_STAGE/install"
    "$HIBREAK_PYTHON" -I "$HIBREAK_BOOTSTRAP_DIR/bootstrap_archives.py" "$HIBREAK_STAGE/platform-tools.zip" "$HIBREAK_STAGE/install" >> "$HIBREAK_LOG" 2>&1 || { hb_fail 'Cannot safely unpack ADB. See the setup log.'; return 1; }
    hb_adb_works "$HIBREAK_STAGE/install/platform-tools/adb" || { hb_fail 'The private ADB runtime does not run on this computer. On Linux, check glibc and system USB libraries; no system software was changed.'; return 1; }
    printf '%s\n' "$HIBREAK_ADB_SHA" > "$HIBREAK_STAGE/install/.archive-sha256"
    [ ! -e "$destination" ] || mv -- "$destination" "$destination.replaced-$(date +%Y%m%d%H%M%S)-$$"
    mv -- "$HIBREAK_STAGE/install" "$destination"
    rm -rf -- "$HIBREAK_STAGE"; HIBREAK_STAGE=
}

hb_main() {
    local dependencies_only=0 explicit_adb= want_adb_value=0 argument
    # Bootstrap options precede wizard options. They never reach the phone wizard.
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --accept-tool-licenses) HIBREAK_ACCEPT_TOOL_LICENSES=1; shift;;
            --check-dependencies) dependencies_only=1; shift;;
            --) shift; break;;
            *) break;;
        esac
    done
    # Honor a caller-supplied ADB before deciding a download is needed. This is
    # especially useful for distribution-provided Linux ARM64/offline installs.
    for argument in "$@"; do
        if [ "$want_adb_value" = 1 ]; then explicit_adb=$argument; want_adb_value=0; continue; fi
        case "$argument" in
            --adb) want_adb_value=1;;
            --adb=*) explicit_adb=${argument#--adb=};;
        esac
    done
    [ "$want_adb_value" = 0 ] || { hb_fail '--adb needs an executable path.'; return 1; }
    hb_platform || return 1
    hb_select_pins || return 1
    [ ! -L "$HIBREAK_CACHE" ] || { hb_fail 'The runtime folder must not be a symbolic link.'; return 1; }
    mkdir -p -- "$HIBREAK_CACHE/logs"
    chmod 700 "$HIBREAK_CACHE" "$HIBREAK_CACHE/logs"
    HIBREAK_LOG="$HIBREAK_CACHE/logs/bootstrap-$(date +%Y%m%d-%H%M%S)-$$.log"
    : > "$HIBREAK_LOG"
    trap hb_cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    hb_say 'HiBreak Auto Scale setup'
    hb_say 'Checking the connection tools. Missing tools stay private to this user; no administrator password is needed.'
    local need_python=1 need_adb=1
    if hb_existing_python; then need_python=0; hb_say 'Using an existing compatible Python runtime.'; fi
    if [ -n "$explicit_adb" ]; then
        hb_adb_works "$explicit_adb" || { hb_fail 'The supplied --adb executable did not pass its version check.'; return 1; }
        HIBREAK_ADB=$explicit_adb; need_adb=0; hb_say 'Using your specified Android connection tool.'
    elif hb_existing_adb; then need_adb=0; hb_say 'Using existing Android connection tools.'; fi
    if [ "$need_python" = 1 ] || [ "$need_adb" = 1 ]; then
        hb_lock || return 1
        [ "$need_python" != 1 ] || hb_install_python || return 1
        [ "$need_adb" != 1 ] || hb_install_adb || return 1
    fi
    hb_say "Python: $HIBREAK_PYTHON"
    hb_say "ADB: $HIBREAK_ADB"
    hb_unlock
    if [ "$dependencies_only" = 1 ]; then hb_say 'Both tools passed their startup checks. No phone was contacted.'; return 0; fi
    local entry="$HIBREAK_BOOTSTRAP_DIR/setup.py"
    [ -f "$entry" ] || entry="$HIBREAK_BOOTSTRAP_DIR/commonsetup.py"
    [ -f "$entry" ] || entry="$HIBREAK_BOOTSTRAP_DIR/setup_on_mac.py"
    [ -f "$entry" ] || { hb_fail 'The setup wizard is missing. Extract the complete kit into one folder.'; return 1; }
    hb_say 'Tools are ready. Starting the phone setup…'
    "$HIBREAK_PYTHON" -E -s "$entry" --adb "$HIBREAK_ADB" --state-dir "$HIBREAK_CACHE/setup-records" "$@"
}

if [ "${HIBREAK_BOOTSTRAP_SOURCE_ONLY:-0}" != 1 ]; then hb_main "$@"; fi
