# Development

## Components

| Path | Purpose |
| --- | --- |
| `source/companion/` | Android foreground companion: car detection, guarded apply/restore, backup and status UI |
| `source/bridge/` | Runtime-discovered vendor interface and restricted display-policy operations |
| `hibreak_aa.py` | Advanced standard-library Python policy CLI |
| `setup.py`, `setup_on_mac.py`, `setup_ui.py`, `setup_assistant.py` | Shared phone setup, exact UI checks and assistant prerequisites; historical filenames retain Mac wording |
| OS launchers and bootstrap files | Private Python/ADB acquisition and shared wizard startup |
| `runtime-downloads.json` | Pinned dependency URLs and hashes |
| `release.json` | Distributed APK/version/signing identity |
| `tests/`, `source/*/test*` | Host-only synthetic checks |
| `scripts/verify_release.py`, `scripts/package_release.py` | Public payload verification and deterministic release packaging |
| `testing/` | Optional official Desktop Head Unit runner and representative profiles |

The fix changes Bigme's per-app density for installed Android Auto, Maps and Google. It does not change global phone density. Native Android Auto-owned `GhFacetBar`/`Dashboard` surfaces choose density; app-generated virtual displays do not. Public selected-device Bluetooth signals can prepare the last learned density before projection. Native display state has priority over Bluetooth detach.

Every actual field change has a persisted journal before its setter, a checked setter result, independent effective readback, vendor persisted-policy reload and collateral-field verification. The automatic helper owns only DPI and its enable flag. Original settings, hardware identity, firmware/schema and row presence are retained per phone. It preserves external edits and pauses on conflicts or firmware/interface drift.

The Android app uses no root, shell-UID daemon, arbitrary Intent command runner, accessibility, device administration, screen-capture or network permission. It runs the fixed allowlisted bridge requests with its own normal application UID. See [companion internals](../source/companion/README.md) and [manual CLI details](manual-cli.md) for the deeper contract.

## Build

Use JDK 17, Android SDK platform 34, and build-tools 35.0.1. Build scripts use `ANDROID_SDK_ROOT`, or default to `source/android-sdk/`; set `JAVA_HOME` to your JDK instead of relying on the original Mac-specific fallback. SDK tools/terms are separate from the end-user runtime bootstrap.

From the repository root:

```sh
export JAVA_HOME=/absolute/path/to/jdk17
export ANDROID_SDK_ROOT=/absolute/path/to/android-sdk
sh source/bridge/build.sh
sh source/companion/build.sh
```

Outputs are `source/bridge/build/display-policy-bridge.jar` and `source/companion/build/hibreak-autoscale.apk`. The companion build embeds the sibling bridge before DEX, alignment, signing and verification. Install the SDK packages with Google's SDK Manager after reviewing its terms: `platforms;android-34` and `build-tools;35.0.1`.

Build scripts generate a local prototype signing key under `source/companion/signing/` if none exists. **That key differs from the published release key.** Your APK cannot replace the release APK through an ordinary data-preserving update. Never clear or uninstall an active recovery state to bypass a signing/version mismatch. Preserve your own key privately for compatible local updates; no signing key or password belongs in Git or a release.

Source builds are not claimed byte-identical to the distributed APK. The release APK identity is recorded in `release.json` and [verification](verification.md).

## Host checks

These checks do not contact a phone:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
pwsh -NoProfile -File tests/test-windows-bootstrap.ps1 -PythonExecutable /path/to/python3
pwsh -NoProfile -File tests/test-windows-dependencies.ps1
sh source/bridge/test-host.sh
sh source/companion/test/run-host-density-tests.sh
sh source/companion/test/run-preparation-tests.sh
sh source/companion/test/run-car-signal-tests.sh
sh source/companion/test/run-policy-rows-tests.sh
sh source/companion/test/run-idle-updates-tests.sh
sh source/companion/test/recovery/run.sh .
```

Build the bridge/app first for suites that use their compiled classes; those Java suites need the SDK/JDK above. The recovery harness requires only JDK 17 and compiles the unchanged production engine against synthetic boundary stand-ins; it needs no Android SDK or phone. Its 108 assertions across 18 fault cases check ordering, classification, conflicts and recovery decisions. It does not emulate AtomicFile durability, actual Binder/vendor SQLite behavior or Android framework process death. See its [README](../source/companion/test/recovery/README.md) for the exact boundary.

Current local results include 128 Python tests, 66 PowerShell bootstrap plus 5 dependency-only checks, the Java contracts and full production Android compilation. [Verification](verification.md) records individual suite counts. Native GitHub CI remains pending until its runs complete. Optional locally captured fixtures must stay private.

## Manual CLI and simulator

Stop and restore the companion and keep monitoring off before manual CLI apply/restore. Do not let two controllers write the same policies. Use an explicit ADB serial when multiple phones may be connected. The CLI saves an operation audit and a new own-phone backup before mutation; it refuses identity, schema, ownership and persistence mismatches rather than inventing defaults. [CLI reference](manual-cli.md) explains partial failures and row-presence differences.

For optional simulator checks, install Google's official [Desktop Head Unit](https://developer.android.com/training/cars/testing/dhu) separately and follow [testing/README.md](../testing/README.md). Profiles are probes, not assertions of compatible receiver modes. The tested phone rejected 1920 × 1080. Keep head-unit developer/server setup, audio protocol checks, screenshot inspection and cleanup explicit. A successful host/simulator run is not physical-car acceptance.

## Releases and contributions

Verify the public payload from the repository root:

```sh
python3 scripts/verify_release.py
python3 scripts/verify_release.py --android-tools "$ANDROID_SDK_ROOT/build-tools/35.0.1"
```

The first command checks the tracked-file allowlist, metadata, APK hash and embedded bridge. The Android-tools option additionally checks the original APK's cryptographic signing certificate and binary manifest. A fresh source-build APK is a compile/signing test only; release packaging retains the original APK with the recorded update signer.

Commit the reviewed public source before packaging, then use a new output folder:

```sh
python3 scripts/package_release.py --output /absolute/path/to/new-output \
  --android-tools "$ANDROID_SDK_ROOT/build-tools/35.0.1"
```

The packager requires clean committed tracked source. It creates `HiBreak-Auto-Scale.apk`, `HiBreak-Auto-Scale-Setup-v1.1.1-beta.1.zip` and `SHA256SUMS`, refusing existing asset paths. The ZIP contains only curated tracked public files, adds per-file checksums, and uses fixed timestamps/permissions for deterministic bytes. The scripts never publish automatically. CI builds a local test-key APK separately, verifies the original shipped payload, and packages that original rather than the compile output.

Keep release metadata, APK hashes, checksums, documentation and packaged files consistent. Keep signing material and phone records out of Git and release archives. Raw diagnostics, logs, private UI captures and per-phone backup/car preferences are not public test fixtures.

Useful next checks are genuine new-device installation, native OS/USB smoke tests, actual Android process/storage interruptions beyond the synthetic recovery boundaries, and separate reproduced halo behavior across app transitions. Describe evidence precisely: host fixture, simulator, measured device behavior or user-reported car result. Do not infer broad battery gains from launcher hiding or short stationary samples.
