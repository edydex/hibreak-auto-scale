#!/bin/sh
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=$(dirname "$test_dir")
jdk_dir=${COMPANION_JAVA_HOME:-${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}}
classes="$app_dir/build/preparation-test-classes"
mkdir -p "$classes"
"$jdk_dir/bin/javac" -source 8 -target 8 -d "$classes" \
    "$app_dir/src/org/hibreak/autoscale/PreparationWindow.java" "$test_dir/PreparationWindowTest.java"
"$jdk_dir/bin/java" -classpath "$classes" org.hibreak.autoscale.PreparationWindowTest
