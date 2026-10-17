# Verification

This page summarizes evidence for the released components. Historical measurements and [performance notes](performance.md) keep version-specific results separate from hardware still needing acceptance.

## Released Android companion

| Field | Value |
| --- | --- |
| Package | `org.hibreak.autoscale` |
| Version | `1.1.1` / code `12` |
| APK | `HiBreak-Auto-Scale.apk` |
| APK SHA-256 | `eb5ed4a486be321c8c00c0550699f019dcb725ff517b59a320ab70134a9e9537` |
| Signer certificate SHA-256 | `dfebc984be01f64f0a084225cbf591bed77f9d89811c58d055264030c17bef85` |
| Build | Non-debuggable; original update signer retained |

The setup revision can change without changing the APK. `release.json` is the authoritative machine-readable version/hash record.

## Public beta release validation

The first public release is tagged **v1.1.1-beta.1**. Its companion remains 1.1.1/code 12; this is a distribution prerelease, not an Android version downgrade. Local release checks passed as listed below. [Native release CI](https://github.com/edydex/hibreak-auto-scale/actions/runs/39076339325) passed on 17 October 2026: macOS 14 ARM64, Ubuntu 24.04 x86_64 and Windows Server 2022 x86_64, plus the Android build and packaging job. These checks do not imply a new physical-phone or receiver acceptance test.

## Phone and desktop-head-unit checks

The oversized interface was reproduced on the HiBreak. At 800 × 480 / native 160 DPI, the bottom bar measured 138 pixels before correction and 80 pixels afterward. The ratio matched the phone policy's 276 DPI versus host 160 DPI. Maps had its own 280-DPI phone policy. App-generated virtual displays were rejected as density references because they could already contain the inflated value.

Version 1.1.0 passed actual paired-desktop Bluetooth-triggered first-frame trials with two seconds and zero intentional delay before the desktop head unit launched. These used genuine Android connection delivery, no Prepare tap or fake app broadcasts. Desktop startup still takes time; this does not establish a physical car's Bluetooth lead time. Real Bluetooth detach preserved car density while projection stayed active, followed by independent full effective-field restoration after projection ended. A subsequent user report confirmed correct immediate automatic scaling in the actual wireless Elantra.

Exact version 1.1.1 checks established:

- Installation preserved the signing identity and recovery data.
- Fresh desktop-head-unit projection had normal Maps controls and the corrected native 80-pixel bar.
- A known recorded request, “Search for gas stations in Seattle,” traversed the official DHU microphone path, was transcribed, and produced matching projected Maps results after launcher pruning.
- Independent post-disconnect readback matched every original effective display-policy field for Android Auto, Maps and Google.
- Automatic mode, the chosen car, required grants/exemption, hidden notification category and vendor background lock remained in place. Temporary debugging/test-server state was cleaned up and original sleep settings were preserved.

The final short voice check had no reported DHU decoder errors. Older DHU sessions did emit decoder errors; they are not sustained video-stability passes. Recorded speech is a protocol test, not a live car microphone/speaker test.

Version 1.1.1 removes duplicate unchanged idle-state saves, repeated identical notification posts and visible status redraws. The previous build saved 510,256 bytes about every 30.2 seconds while idle; a settled 30-second v12 observation retained its display check with zero unchanged saves. Necessary commits and write verification remain. No matching-scene final CPU benchmark or defensible battery/frame-rate percentage improvement was established.

## Host and installer checks

The following local checks passed for the public release:

| Check | Result |
| --- | --- |
| Python host/installer/bootstrap/release tests | 128 tests |
| PowerShell bootstrap fixtures, run on Mac | 66 checks plus 5 dependency-only checks |
| Vendor bridge contracts | 3 success, 5 failure and 15 protocol checks |
| Native display-density parser | 29 checks |
| Preparation timing and lifecycle | 15 checks |
| Selected-car signal policy | 32 checks |
| Production policy-row parser | 54 checks |
| Idle persistence and notification decisions | 110 checks |
| Production recovery engine with synthetic boundaries | 108 assertions across 18 fault cases |
| Android production source | Full compilation, DEX, alignment, local test signing and verification passed |

The build check generated a local test-key APK. **Only the original shipped APK with the signer above is a release payload**; the compile output does not replace it. The release verifier checks its expected hash and, with Android build tools supplied, its cryptographic signer and binary manifest.

The recovery suite compiles the unchanged production `ScaleEngine`, `HostDensity` and `PreparationWindow`. Synthetic Android/JSON/store/bridge boundaries exercise journal-before-setter ordering, failure classification, persisted-policy readback, conflict preservation and restoration. A fresh engine loads the last independently committed state snapshot to model a restart. These tests do not establish Android AtomicFile durability, actual vendor database/cache behavior or framework process death. See the [recovery harness contract](../source/companion/test/recovery/README.md).

[Native CI](https://github.com/edydex/hibreak-auto-scale/actions/runs/39076339325) passed all four jobs. The Mac and Linux jobs ran all 128 Python tests; Windows ran the same discovery with 27 POSIX/symlink-specific skips and passed 66 bootstrap plus 5 dependency-mode checks in Windows PowerShell 5.1. All three hosts forced missing-tool discovery and performed real pinned Python/ADB downloads, hash verification, extraction and executable startup without starting ADB or contacting a phone. Windows used embedded Python 3.13.16 AMD64; Mac/Linux used Python 3.12.15. Android CI provisioned its own pinned command-line tools, compiled the production source with JDK 17, ran the Java contracts/recovery tests, cryptographically verified the original APK and produced two byte-identical release kits. Physical USB authorization, drivers and a new phone/receiver remain separate acceptance work.

Synthetic host checks do not access Bluetooth radios or replace final-build hardware acceptance. Exact suite commands are in [development](development.md); consult the release workflow results for the run attached to that release.

## Still requiring hardware acceptance

1. A genuine fresh setup on another HiBreak, including its independent backup, normal USB authorization, chosen car, first learning, later automatic connection and restoration.
2. Physical head-unit voice input, audible response, steering-wheel activation and call audio on the current APK.
3. Sustained locked-phone/background survival, reboot/unlock and repeated drive transitions on the final build.
4. Native host installation and USB flow on additional Intel Mac, Linux and Windows systems, beyond shared host tests.
5. Actual Android process death and storage durability around journal/setter/commit boundaries, real vendor database/cache failure behavior, and firmware-update recovery review. The synthetic production-engine fault suite covers specified logic paths, not these hardware/framework guarantees.

When reporting a new result, record model, firmware, app version, receiver, connection type, host OS and whether the result was simulated, directly measured or user-reported. Keep raw backups, account/UI captures and Bluetooth/device identities private.
