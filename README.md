# HiBreak Auto Scale

[![Checks](https://github.com/edydex/hibreak-auto-scale/actions/workflows/checks.yml/badge.svg)](https://github.com/edydex/hibreak-auto-scale/actions/workflows/checks.yml)

Fix oversized Android Auto controls on the Bigme HiBreak, then restore the phone's normal app density after disconnecting.

The Android companion learns the receiver's actual display density. Selecting your paired car once lets its Bluetooth connection prepare Android Auto, Maps and Google before projection starts. **Prepare for car** remains available as a fallback. Each phone keeps its own recovery data; no fixed car DPI or another phone's settings are installed.

**Public beta.** Tested on one HiBreak S firmware. A user reported immediate correct automatic scaling in a 2023 Hyundai Elantra Hybrid Blue on companion 1.1.0. The current companion is **1.1.1 / code 12** and has exact-build phone/simulator evidence. More phones, physical receivers and host computers still need acceptance testing. See [compatibility](docs/compatibility.md) and [verification](docs/verification.md).

## Install

1. Download the complete **HiBreak-Auto-Scale-Setup-v1.1.1-beta.1.zip** from the [v1.1.1-beta.1 release](https://github.com/edydex/hibreak-auto-scale/releases/tag/v1.1.1-beta.1), then extract it. Use the release kit rather than GitHub's automatically generated source archive.
2. Unlock the phone, enable **Developer options → USB debugging**, disconnect Android Auto, and connect the phone with a data-capable USB cable.
3. Run the launcher for your computer:

   | Computer | Launcher |
   | --- | --- |
   | Mac | Double-click `Setup-on-Mac.command` |
   | Linux | Run `bash Setup-on-Linux.sh` |
   | Windows | Double-click `Setup-on-Windows.cmd` |

The launcher finds Python and ADB or downloads checksum-pinned private copies. It needs no Homebrew, pip, administrator installation or global PATH changes. First-use SDK terms, USB authorization and normal operating-system security prompts still require you.

Follow the phone prompts to **padlock the helper in Bigme Recents** and **choose your actual paired car**. The wizard checks these steps instead of asking you to repeatedly confirm them. At the first parked car connection, check scaling, voice/call audio and restoration after disconnect. A new receiver may need one quick reconnect after its density is learned.

[Full setup and troubleshooting](docs/setup.md) · [Undo and recovery](docs/undo.md)

## What setup changes

- Saves this phone's own original display policies before configuration, installs the signed APK, and enables its guarded automatic mode.
- Grants only the helper's required diagnostic, notification and paired-device access, adds its Android idle exemption, and hides its status notification category.
- Turns automatic media startup off. By default, optional launcher entries keep **Maps, Messages, Reminder, Heritage and NewPipe**; protected built-in entries remain. You can choose a different list.
- Turns off the recognized phone Maps raised-buildings preference. The separate setting inside projected Maps remains a parked-car step.
- Checks Google's assistant role/service and microphone access while in use. An existing different assistant requires your choice. Wake-word preferences are preserved.

Hiding launcher icons does not disable their phone apps or prove lower CPU use. The companion avoids redundant idle-state writes, but no whole-device speed or battery gain is claimed. [Performance notes](docs/performance.md) explain the measurements.

## Normal use and removal

Keep the helper's Bigme Recents padlock enabled. After both the selected car connection and Android Auto end, the helper restores the display fields it still owns. Those apps may look smaller on the phone while the car is connected or prepared.

**Use Stop and restore and wait for success before uninstalling, clearing app storage or revoking diagnostic access.** Maps, launcher, media and assistant preferences are separate from the density backup. Firmware/interface changes intentionally pause writes; restore before installing a phone firmware update. [Undo and firmware recovery](docs/undo.md) cover these cases.

## Project

The project contains the Android companion, a runtime-discovered Bigme display-policy bridge, a guarded manual CLI, cross-platform setup launchers and synthetic host tests. It needs no root, bootloader unlock or accessibility service. The Android companion has no network permission; the computer launcher uses the network only when it needs dependencies.

[Development and tests](docs/development.md) · [Evidence and remaining checks](docs/verification.md) · [License](LICENSE)

Related research: [joemk88/hibreak-android-auto-fix](https://github.com/joemk88/hibreak-android-auto-fix) investigates dark halos and text enhancement, a separate symptom. Its investigation is useful context; this project's normal setup does not permanently turn text enhancement off, and no implementation code was copied from it.

Before opening an issue, remove device IDs, account data, car Bluetooth addresses and private backups. Raw setup reports, diagnostics and UI captures can contain this information. Report the phone model/firmware, companion version, host OS, receiver and a short description of what happened.
