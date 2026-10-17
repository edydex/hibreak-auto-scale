#!/bin/sh
set -eu
COMPANION_TEST_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPANION_TEST_CLASSES=$(mktemp -d "${TMPDIR:-/tmp}/hibreak-density-test.XXXXXX")
COMPANION_TEST_JDK=${COMPANION_JAVA_HOME:-${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}}
trap 'rm -rf "$COMPANION_TEST_CLASSES"' EXIT HUP INT TERM
"$COMPANION_TEST_JDK/bin/javac" -d "$COMPANION_TEST_CLASSES" \
  "$COMPANION_TEST_ROOT/src/org/hibreak/autoscale/HostDensity.java" \
  "$COMPANION_TEST_ROOT/test/HostDensityTest.java"
if [ "$#" -gt 0 ]; then
  "$COMPANION_TEST_JDK/bin/java" -cp "$COMPANION_TEST_CLASSES" HostDensityTest "$1"
else
  "$COMPANION_TEST_JDK/bin/java" -cp "$COMPANION_TEST_CLASSES" HostDensityTest
fi
