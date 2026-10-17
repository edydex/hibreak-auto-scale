#!/bin/sh
set -eu
bridge_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sdk_dir=${ANDROID_SDK_ROOT:-"$bridge_dir/../android-sdk"}
jdk_dir=${BRIDGE_JAVA_HOME:-${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}}
android_jar=${BRIDGE_ANDROID_JAR:-"$sdk_dir/platforms/android-34/android.jar"}
test_classes="$bridge_dir/build/test-classes"
mkdir -p "$test_classes"
"$jdk_dir/bin/javac" -source 8 -target 8 -classpath "$android_jar:$bridge_dir/build/classes" \
    -d "$test_classes" "$bridge_dir/test/org/json/JSONObject.java" \
    "$bridge_dir/test/org/json/JSONArray.java" \
    "$bridge_dir/test/xrz/framework/manager/DisplayPolicy.java" \
    "$bridge_dir/test/BridgeWriteTest.java" "$bridge_dir/test/BridgeProtocolTest.java"
"$jdk_dir/bin/java" -classpath "$test_classes:$bridge_dir/build/classes:$android_jar" BridgeWriteTest
"$jdk_dir/bin/java" -classpath "$test_classes:$bridge_dir/build/classes:$android_jar" BridgeProtocolTest
