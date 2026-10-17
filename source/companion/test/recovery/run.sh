#!/bin/sh
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Explicit repository/kit path keeps this test directory relocatable.
root=${1:?Pass the repository or extracted kit root as the first argument}
app_src="$root/source/companion/src/org/hibreak/autoscale"
jdk_dir=${COMPANION_JAVA_HOME:-${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}}
classes=$(mktemp -d "${TMPDIR:-/tmp}/hibreak-recovery-tests.XXXXXXXX")
trap 'rm -rf "$classes"' EXIT HUP INT TERM
find "$test_dir/stubs" -name '*.java' > "$classes/inputs.txt"
printf '%s\n' "$app_src/ScaleEngine.java" "$app_src/HostDensity.java" "$app_src/PreparationWindow.java" "$test_dir/RecoveryTest.java" >> "$classes/inputs.txt"
"$jdk_dir/bin/javac" -source 8 -target 8 -Xlint:all -d "$classes" "@$classes/inputs.txt"
"$jdk_dir/bin/java" -classpath "$classes" org.hibreak.autoscale.RecoveryTest
