#!/bin/sh
set -eu

app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sdk_dir=${ANDROID_SDK_ROOT:-"$app_dir/../android-sdk"}
jdk_dir=${COMPANION_JAVA_HOME:-${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}}
android_jar=${COMPANION_ANDROID_JAR:-"$sdk_dir/platforms/android-34/android.jar"}
tools_dir=${COMPANION_BUILD_TOOLS:-"$sdk_dir/build-tools/35.0.1"}
build_dir="$app_dir/build"
key_store="$app_dir/signing/probe-keystore.jks"
password_file="$app_dir/signing/probe-password.txt"

mkdir -p "$build_dir/classes" "$build_dir/dex" "$build_dir/generated" "$app_dir/signing" "$app_dir/assets"
cp "$app_dir/../bridge/build/display-policy-bridge.jar" "$app_dir/assets/display-policy-bridge.jar"
if [ ! -f "$password_file" ]; then
    umask 077
    /usr/bin/openssl rand -hex 24 > "$password_file"
fi
if [ ! -f "$key_store" ]; then
    "$jdk_dir/bin/keytool" -genkeypair -keystore "$key_store" -storepass:file "$password_file" \
        -keypass:file "$password_file" -alias hibreak-probe -keyalg RSA -keysize 2048 \
        -validity 10000 -dname 'CN=HiBreak Auto Scale Local Prototype'
fi
"$tools_dir/aapt2" link -o "$build_dir/base.apk" --manifest "$app_dir/AndroidManifest.xml" \
    -I "$android_jar" --java "$build_dir/generated" --min-sdk-version 26 --target-sdk-version 34 \
    -A "$app_dir/assets"
find "$app_dir/src" -name '*.java' > "$build_dir/java-inputs.txt"
"$jdk_dir/bin/javac" -source 8 -target 8 -Xlint:all -classpath "$android_jar" \
    -d "$build_dir/classes" "@$build_dir/java-inputs.txt"
find "$build_dir/classes" -name '*.class' > "$build_dir/class-inputs.txt"
JAVA_HOME="$jdk_dir" "$tools_dir/d8" --lib "$android_jar" --min-api 26 \
    --output "$build_dir/dex" "@$build_dir/class-inputs.txt"
cp "$build_dir/base.apk" "$build_dir/unsigned.apk"
(cd "$build_dir/dex" && /usr/bin/zip -q "$build_dir/unsigned.apk" classes.dex)
"$tools_dir/zipalign" -f 4 "$build_dir/unsigned.apk" "$build_dir/aligned.apk"
JAVA_HOME="$jdk_dir" "$tools_dir/apksigner" sign --ks "$key_store" --ks-key-alias hibreak-probe \
    --ks-pass "file:$password_file" \
    --out "$build_dir/hibreak-autoscale.apk" "$build_dir/aligned.apk"
# Retain the earlier test-harness filename as an identical compatibility alias.
cp "$build_dir/hibreak-autoscale.apk" "$build_dir/hibreak-autoscale-probe.apk"
JAVA_HOME="$jdk_dir" "$tools_dir/apksigner" verify --verbose "$build_dir/hibreak-autoscale.apk"
"$tools_dir/aapt2" dump badging "$build_dir/hibreak-autoscale.apk"
/usr/bin/shasum -a 256 "$build_dir/hibreak-autoscale.apk"
