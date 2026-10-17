# HiBreak Auto Scale

Native Android companion `org.hibreak.autoscale`, version code 12 / `1.1.1`,
minimum Android API 26, target API 34. It follows Android Auto's native display DPI
and restores its own per-app DPI changes after a ten-second disconnect grace.
It does not restart Android Auto or change text enhancement, global density,
refresh settings, or other display-policy fields.

Choose **Automatic for paired car** once to recognize your already-paired car's
Bluetooth connection. Its connecting/connected events run verified preparation
using the last validated native host DPI before projection starts. There is no
Bluetooth scan or pairing, and no location permission. Select only your car.

Automatic mode needs the car Bluetooth event to arrive early enough. The measured
warm verified preparation path is about 1.85 seconds on this phone; actual Elantra
Bluetooth-to-projection lead time has not yet been measured. On version 11 / 1.1.0,
the user reported that the first real Elantra connection operated automatically
with correct scaling immediately. That visual report did not instrument the car's native DPI or timing,
or verify its voice/audio path. The current 160-DPI starting point was learned
from the test head unit.
A real host advertising a different DPI is learned live and may need one quick
reconnect. Other car connection timings still need their own acceptance check.

**Prepare for car** remains the fallback: wait for **Ready** before connecting.
This firmware constructs Android Auto bars and Maps containers at the density
present when projection starts. Live correction alone leaves those containers
oversized until reconnect, including later drives after phone settings restore.
The app prepares all three packages at the learned car DPI in advance and then
restores phone preferences after the drive. It cannot remove this firmware
first-frame constraint without automatic or manual advance preparation, or a reconnect.

## Setup and use

Build with `./build.sh` using the local Android SDK/JDK, or install the signed
`build/hibreak-autoscale.apk`. An identical `hibreak-autoscale-probe.apk` alias is
retained for the earlier local test harness.
Retain the local signing key in `signing/` for compatible updates. The key and its
password are build inputs and should not be distributed to end users.

For a positively identified ADB target:

```sh
adb -s SERIAL install -r build/hibreak-autoscale.apk
adb -s SERIAL shell pm grant org.hibreak.autoscale android.permission.DUMP
adb -s SERIAL shell am start -n org.hibreak.autoscale/.MainActivity
```

1. Disconnect Android Auto before the first enable. The app refuses to capture
   original phone preferences while any Android Auto display is present or the
   display state is uncertain.
2. For first use, tap **Enable detection / learn car** and allow the requested
   notification permission. Its visible status notification can then be hidden
   by category as described below. Allow the app to continue
   running using the verified Bigme route: **Recents → Process manage → lock the
   HiBreak Auto Scale card with its padlock**. Clear All preserves the locked card;
   individually swiping away that card removes the lock. Android's idle exemption
   alone does not set this separate vendor process lock.
3. Connect once to learn the car DPI. Wait for scaling to finish, then quickly
   disconnect/reconnect within the ten-second restoration grace to recreate the
   bar and Maps containers at the correct density. This is also the fallback for
   **every fresh unprepared connection**, not only the first/new car. The app
   does not force-stop Android Auto, which would interrupt a real car session.
4. Tap **Automatic for paired car**, grant Nearby devices access, and choose the
   already-paired car. This is one-time setup; normal subsequent connections trigger
   preparation automatically. The car's Bluetooth presence is not evidence that
   Android Auto is projecting. Native display detection independently confirms
   projection and checks its actual DPI. A stale connection hint expires after
   sixty seconds without a fresh connection event or public profile confirmation.
5. If the automatic signal arrives too late, **Prepare for car** is available
   while disconnected. Wait for **Ready**, then connect within ten minutes. It uses the last validated native
   host DPI, preflights every installed target, preserves the existing original
   backup, and verifies all changes before reporting Ready.
   A fresh display check after the writes also confirms the car did not connect
   early. Early connection keeps the reconnect-needed warning; an uncertain check
   preserves prepared settings without reporting Ready until a reliable recheck.
   A different car/DPI is learned live and may need the quick reconnect again.
   If no car connects,
   the next idle check after ten minutes restores owned settings. A reboot while
   merely prepared cancels preparation and restores if no car display is present.
6. In automatic mode, car DPI stays ready while the selected Bluetooth car is
   connecting/connected, even before or after projection. Phone settings restore
   only after **both Android Auto and the selected car connection are gone**, with
   the ten-second display grace. Thus these three apps may look smaller on the
   phone while that car remains connected. Only still-owned fields are restored.
7. **Stop and restore** disables automatic car arming and monitoring, cancels preparation, and restores owned fields immediately.
   Use this before uninstalling, clearing storage, or revoking DUMP. **Refresh
   status** triggers an immediate display check without enabling an off session.
8. **Export saved backup** opens Android's file picker and saves one complete
   committed JSON snapshot of the original settings, runtime schema, row presence,
   and transaction/recovery history to the location you choose. Nothing is exported
   automatically. Keep this personal file private; it supports recovery on this
   phone and is not a general backup to apply to another phone. Exporting does not
   change scaling, start monitoring, or import any settings, and needs no additional
   permission.

The app starts its saved enabled session after reboot or package replacement.
If it finds a saved pending write, it reloads the vendor database and resolves
that transaction before applying or restoring settings. Android force-stop,
cleared app data, or a vendor background-task killer can prevent automatic
operation; manually opening the app and refreshing resumes saved recovery.

## How it chooses density

Only Android Auto-owned native `DisplayDeviceInfo` entries named `GhFacetBar` or
`Dashboard` choose the target. The preferred source is GhFacetBar; all selected
main surfaces and Android Auto-owned cluster surfaces must agree on a DPI in
72–640. CarAppService, templates, and app-drawn virtual displays are excluded:
the firmware can create those using already-corrupted application density.
Unknown, conflicting, malformed, inactive, or out-of-range host information causes
no new writes and preserves existing owned preferences through negotiation.

Public display callbacks trigger an immediate dump. One serialized worker also
polls every two seconds while connected or waiting through detach, and every
thirty seconds when idle. There are no overlapping workers. Every `dumpsys`
command has an eight-second timeout and one-MiB per-stream output limit.

## Backup, transactions, and restoration

Before enabling, private `files/automatic-state.json` atomically stores the build
fingerprint, runtime bridge/interface schema, physical initial DPI, complete
readback fields, independent raw vendor rows, and original row presence. Raw
vendor rows and effective getter fields are deliberately treated separately:
Bigme normalizes some color-mode fields when reading a policy.

Every installed target is preflighted for `appDpiScale == 1`, `immutable == 0`, and
DPI/flag ownership before the first apply write. Only two fields are owned:
`appDpi` and `isDpiSetting`. Unrelated fields are preserved and checked against
effective before/after policy snapshots. No-op setters are skipped.

Each actual field change first atomically saves a journal containing its complete
before state, desired value, package, and operation. The app requires the setter's
success result, exact readback, a matching raw database field after vendor reload,
and unchanged effective collateral fields before committing ownership and clearing
the pending journal. Interrupted writes are classified only after database reload.
Firmware/schema drift or conflicting recovery state refuses further writes.

The firmware does not persist a DPI-enable flag change at the physical initial
DPI. When needed, the app stages a temporary DPI, changes the flag, then applies
its intended DPI. Each intermediate step is journaled, owned, and verified.
During restoration this staging is refused if it would overwrite an externally
edited DPI. External edits to owned fields are preserved and reported, and an
unrelated edit is retained in subsequent effective policy checks.

A getter may synthesize a default for an absent database row. If its desired
values already match and no setter has been attempted, the app leaves the row
absent. If a change materializes an originally absent row, restoration restores
its original effective values and reports the row-presence difference. This
firmware exposes no row-deletion API, so the app does not claim exact database-row
removal. Full backup and bounded transaction history remain in private storage.

## Access and permissions

The Activity runtime filters vendor reflection methods on this firmware. The
companion bundles the existing bridge as an APK asset, writes private read-only
code, then launches fixed allowlisted `app_process` commands with the unchanged
normal app UID. It uses the actual vendor AIDL Stub and reflection, without
hardcoded transaction IDs, root, a shell-UID daemon, or arbitrary Intent commands.
The native bridge JAR itself supports a small diagnostic CLI; the automatic app
invokes only inspect, package reads, DPI setter, and DPI-enable setter. Version 4
keeps one same-UID child runtime open for serialized private JSON-line requests,
avoiding Android runtime startup on every policy read or field write. The helper
reuses its live Binder proxy. It returns full schema only for inspection and
compact policy/method/readback results for get/set. Each response has a bounded
timeout, child death restarts the helper on the next request, and service shutdown
destroys the helper. The transaction journal remains the boundary before each
individual field write; batching does not combine or bypass those checks.

Permissions are DUMP (one-time ADB development grant), foreground service and
special-use foreground service, notifications, boot completed, and Bluetooth
connect for a selected paired car (Nearby devices on Android 12+; legacy normal
Bluetooth permission is capped to Android 11 and earlier). Bluetooth scanning and
location access are not used. There is no INTERNET, READ_LOGS, accessibility service,
device administrator, or screen capture.

Notification visibility is optional. In **App info > Notifications > Automatic
Android Auto scaling**, turn off only that category to hide the notification row.
Leave the overall notification permission granted because the current setup
controls request it. Keep the foreground service running, Nearby devices access,
the Android idle exemption, and the Bigme process padlock. Do not stop or demote
the service to hide its notification. Android can retain an Active apps entry.
The existing APK needs no update: re-enabling the same category restores its
visible status and **Stop and restore** action. Stop and restore also remains
available inside the app when the category is hidden.
After unhiding it, open the helper or tap **Refresh status** if the notification
does not reappear immediately; unchanged polling no longer reposts its row.

On the tested phone, blocking that category produced channel importance 0 and no
active notification record while the helper remained a foreground service.
The app still supplies its required service notification; Android controls its
visibility. See Android's [notification permission behavior](https://developer.android.com/develop/ui/compose/notifications/notification-permission)
and [channel settings](https://developer.android.com/develop/ui/compose/notifications/channels).

The **Read-only diagnostics** screen retains the earlier access/display probe.
It saves `probe.json` in external app files and logs numbered `HBAutoScale` chunks.
Diagnostics do not invoke bridge setters or enable monitoring.

## Build and validation boundaries

`./build.sh` compiles Java and resources, creates DEX, aligns and signs the APK,
then verifies its signature and manifest. `sh test/run-host-density-tests.sh` runs synthetic parser checks. An optional
path to your own private saved display dump adds real-fixture checks; no private
phone dump is included in this kit. Bridge reflection
write-failure tests are in the sibling `../bridge/test-host.sh`.
`sh test/run-preparation-tests.sh` runs 15 clock, timeout, host-arrival, process,
and boot transition checks for the preparation hold.
`sh test/run-car-signal-tests.sh` checks selected-device connection aggregation,
ACL epochs, startup snapshots, stale-proof expiry, and permission/lifecycle guards.

The version 12 / 1.1.1 APK is non-debuggable and uses the same local signing key as
the tested development versions. Its field writes retain per-step database reload
and full readback verification; redundant package-level verification is skipped
only when a changed field has already completed those checks. No-op configurations
retain persistence checks. A fresh enabled idle session now shows “Waiting for
Android Auto” immediately when there are no owned settings needing restoration.

Successful compilation and host checks alone do not establish automatic apply,
detach restore, reboot recovery, or real-car layout acceptance. Repeat those
device checks on the final non-debuggable APK before claiming final acceptance.

The final version 11 APK passed actual phone/desktop Bluetooth-triggered
first-frame trials at two-second and zero intentional DHU-launch delays, without
a Prepare tap, fake app broadcast, or reconnect. The complete zero-delay sequence
also verified that real Bluetooth detach preserves car DPI while native AA stays
active, then restores all original effective fields after AA exits. DHU still
has startup/negotiation time after launch; these bench results do not establish
the real Elantra's timing or native DPI. Separately, on version 11 / 1.1.0 the user
reported correct scaling immediately on its first real automatic Elantra connection.
This was not an instrumented native-DPI/timing capture or a full car voice/audio test. See the
[verification guide](../../docs/verification.md) for evidence boundaries and remaining checks.

Version 9 adds concise monotonic timing records under Android log tag
`HBAutoPerf`: bridge RPC duration and warm/cold status, fixed dump duration, state
save lock wait/serialization/write/commit duration and byte count, and preparation
start/completion. Commit includes AtomicFile's sync/close/rename work. These logs
contain no policy dumps or exported backup data, add no permissions, and do not
change the journal or scaling behavior.

Version 10 reuses precompiled policy-row/integer/decimal regular expressions and
method-local numeric matchers, preserving the prior parsing rules and malformed /
duplicate guards. `HBAutoPerf` also reports `parse-rows` duration/count/success.
`sh test/run-policy-rows-tests.sh` (after the app has been compiled)
checks token/row equivalence, numeric types, malformed values, and duplicate guards
against the production parser with host-only Android/JSON stand-ins. An optional
private local policy dump can add fixture comparisons; none is distributed. These stand-ins
are outside APK sources and are not substitutes for device timing measurements.

Version 12 avoids rewriting an unchanged owned-empty idle state, reposting an
unchanged service notification, and redrawing identical visible status text.
An idle flag/status transition still commits once. Explicit Refresh, re-enabling,
and opening the running helper force publication of its current notification;
after unhiding the notification category, open the helper or tap Refresh if its
row is not immediately visible. Display poll intervals, Bluetooth presence timing,
and every backup/transaction/persistence check are unchanged.
`sh test/run-idle-updates-tests.sh` checks production idle-transition and
notification-decision logic on the host; notification delivery and background
CPU improvements require separate phone measurements.
