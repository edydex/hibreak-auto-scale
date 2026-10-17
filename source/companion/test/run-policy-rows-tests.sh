#!/bin/sh
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=$(dirname "$test_dir")
jdk_dir=${COMPANION_JAVA_HOME:-${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}}
sdk_dir=${ANDROID_SDK_ROOT:-"$app_dir/../android-sdk"}
android_jar=${COMPANION_ANDROID_JAR:-"$sdk_dir/platforms/android-34/android.jar"}
classes="$app_dir/build/policy-rows-test-classes"
mkdir -p "$classes"
"$jdk_dir/bin/javac" -source 8 -target 8 -classpath "$app_dir/build/classes:$android_jar" -d "$classes" \
    "$test_dir/parser-stubs/android/os/SystemClock.java" "$test_dir/parser-stubs/android/util/Log.java" \
    "$test_dir/parser-stubs/org/json/JSONObject.java" "$test_dir/PolicyRowsTest.java"
"$jdk_dir/bin/java" -classpath "$classes:$app_dir/build/classes:$android_jar" org.hibreak.autoscale.PolicyRowsTest "$@"
