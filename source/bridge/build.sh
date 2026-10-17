#!/bin/sh
set -eu

bridge_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sdk_dir=${ANDROID_SDK_ROOT:-"$bridge_dir/../android-sdk"}
jdk_dir=${BRIDGE_JAVA_HOME:-${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}}
android_jar=${BRIDGE_ANDROID_JAR:-"$sdk_dir/platforms/android-34/android.jar"}
d8_bin=${BRIDGE_D8:-"$sdk_dir/build-tools/35.0.1/d8"}
build_dir="$bridge_dir/build"

if [ ! -x "$jdk_dir/bin/javac" ] || [ ! -x "$jdk_dir/bin/java" ]; then
    printf '%s\n' 'A JDK is required. Set BRIDGE_JAVA_HOME to its installation directory.' >&2
    exit 1
fi
if [ ! -f "$android_jar" ] || [ ! -x "$d8_bin" ]; then
    printf '%s\n' 'Android SDK platform 34 and build tools 35.0.1 are required (or set BRIDGE_ANDROID_JAR and BRIDGE_D8).' >&2
    exit 1
fi
mkdir -p "$build_dir/classes" "$build_dir/dex"
"$jdk_dir/bin/javac" -source 8 -target 8 -Xlint:all -classpath "$android_jar" \
    -d "$build_dir/classes" "$bridge_dir/DisplayPolicyBridge.java"
JAVA_HOME="$jdk_dir" "$d8_bin" --lib "$android_jar" --min-api 26 \
    --output "$build_dir/dex" "$build_dir/classes/DisplayPolicyBridge.class"
(cd "$build_dir/dex" && /usr/bin/zip -q "$build_dir/display-policy-bridge.jar" classes.dex)
printf '%s\n' "$build_dir/display-policy-bridge.jar"
