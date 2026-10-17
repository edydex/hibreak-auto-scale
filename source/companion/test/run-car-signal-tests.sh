#!/bin/sh
set -eu
CAR_SIGNAL_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CAR_SIGNAL_JDK=${COMPANION_JAVA_HOME:-${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}}
CAR_SIGNAL_SDK=${ANDROID_SDK_ROOT:-"$CAR_SIGNAL_ROOT/../android-sdk"}
CAR_SIGNAL_ANDROID_JAR=${COMPANION_ANDROID_JAR:-"$CAR_SIGNAL_SDK/platforms/android-34/android.jar"}
CAR_SIGNAL_CLASSES=$(mktemp -d "${TMPDIR:-/tmp}/hibreak-car-signal.XXXXXX")
trap 'rm -rf "$CAR_SIGNAL_CLASSES"' EXIT HUP INT TERM
"$CAR_SIGNAL_JDK/bin/javac" -source 8 -target 8 -classpath "$CAR_SIGNAL_ANDROID_JAR" \
  -d "$CAR_SIGNAL_CLASSES" \
  "$CAR_SIGNAL_ROOT/src/org/hibreak/autoscale/CarSignalPolicy.java" \
  "$CAR_SIGNAL_ROOT/src/org/hibreak/autoscale/BluetoothCarMonitor.java" \
  "$CAR_SIGNAL_ROOT/test/CarSignalPolicyTest.java"
"$CAR_SIGNAL_JDK/bin/java" -classpath "$CAR_SIGNAL_CLASSES" CarSignalPolicyTest
