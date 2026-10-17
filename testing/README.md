# Repeatable HiBreak Android Auto DHU captures

This Python standard-library harness launches Google's installed Desktop Head Unit
(DHU), supplies an explicit configuration, saves its native PNG frames and raw
stdout/stderr, and records commands, image dimensions/hashes, and status in JSON.
It never invokes ADB, edits phone settings, installs software, or writes
`~/.android/headunit.ini`. Running a profile creates a new Android Auto projection
session against a phone whose tunnel has already been prepared.

## Prepare or inspect without a phone

```sh
python3 dhu_test.py prepare
python3 dhu_test.py list
python3 dhu_test.py run 720p160 --dry-run --label before
```

The runner finds a DHU under the kit's `source/android-sdk/extras/google/auto/`
(or a sibling `android-sdk`), then checks `ANDROID_SDK_ROOT` / `ANDROID_HOME`. Alternatively pass
`--dhu /absolute/path/to/desktop-head-unit`. Keep the DHU's bundled libraries beside
its binary. The verified local binary reports `2.0-mac-arm64`, build
`2022-03-30-438482292`; no phone session was run during harness preparation.

## Phone prerequisite, once per connection

1. Enable Android Auto's own developer mode. This is separate from Android system
   developer options. In Android Auto settings, repeatedly tap the version until
   developer mode is enabled; use its overflow menu to **Start head unit server**.
2. Allow new cars under Android Auto's previously connected cars setting. Unlock
   the phone, connect USB, and accept the computer's USB-debugging authorization.
3. In your existing Android platform-tools installation, select the intended phone
   and prepare the tunnel: `adb -s SERIAL forward tcp:5277 tcp:5277`. If multiple
   devices exist, always select the intended serial. The runner does not choose a
   device or create/remove the tunnel.
4. Accept Android Auto's first-connection terms and permissions on the phone.

For a different local port use, for example,
`adb -s SERIAL forward tcp:5999 tcp:5277` then `--port 5999`.

## Capture one profile

```sh
python3 dhu_test.py run 720p160 --label before --interactive
python3 dhu_test.py run 720p160 --label after --note 'Describe exactly what changed'
```

Each command launches a fresh DHU and waits up to 45 seconds for a completed native
PNG, rather than treating process startup as a working projection. It then captures
home and the default navigation app in day and night modes and returns to day mode.
Use `--startup-timeout 60` if a permission prompt needs more time. `--headless` is
available when a visible DHU window is unnecessary. The default four-second wait
between screen changes can be extended with `--settle 8` on this slower phone.

With `--interactive`, the visible DHU still accepts mouse input and the harness
offers a console after automatic captures. Useful commands are:

```text
tap X Y
keycode navigation
keycode home
day
night
screenshot maps-search.png
quit
```

Use the visible navigation screen to open its search field, save `maps-search.png`,
open the keyboard if available, save `maps-keyboard.png`, and capture the app
launcher/tiles. Coordinates depend on the rendered profile; do not replay a
coordinate across different resolutions without checking its target. `home` means
the head unit's home action, which can be dashboard or launcher depending on the
Android Auto version. `navigation` means the configured navigation app and must
not be labeled Maps unless Maps is what actually opened.

The run directory includes a config snapshot, `manifest.json`, `dhu-version.txt`,
`stdout.log`, `stderr.log`, and all PNG captures. Configuration and command paths
are passed as subprocess arguments; console image names are simple relative names,
so workspace paths containing spaces do not break the screenshot command.

## Matrix and evidence interpretation

DHU launch alone does not create an early car Bluetooth signal. To test the
automatic first-frame path, start from independently verified restored phone
preferences, receive a real connection event from the explicitly selected bonded
test device, and launch DHU after a fixed, recorded delay. Do not tap Prepare or
use a fabricated app broadcast in a trial labeled automatic. Record the actual
connection event, completion of all three persisted app policies, first native
AA surface creation, and the first projected frame. A successful bench delay
does not establish a real car's Bluetooth-to-projection lead time or native DPI.
Separately, on version 11 / 1.1.0 the user reported that the first real Elantra
connection operated automatically with correct scaling immediately. That visual report did not
instrument native DPI or timing, or establish voice/audio acceptance.

For the separate manual fallback test, use **Prepare for car** while disconnected,
wait for **Ready**, then launch DHU within ten minutes. Both paths need native DPI
learned from a previous head-unit session. Label an unprepared session separately:
live policy correction can leave cached bar/map containers oversized, so matching
policy values alone cannot count as correct rendering. After teaching a different
DPI, let the app apply it and reconnect within ten seconds to rebuild containers.
Keep manual CLI writes and companion monitoring from running at the same time;
use **Stop and restore** before manual CLI tests.

| Profile | Video frame | Requested logical DPI | Purpose |
| --- | --- | --- | --- |
| 480p160 | 800 x 480 | 160 | Low-resolution baseline |
| 720p160 | 1280 x 720 | 160 | Resolution comparison at the same DPI |
| 720p240 | 1280 x 720 | 240 | Isolate requested DPI at a fixed resolution |
| 720p320 | 1280 x 720 | 320 | Higher logical density at the tested 720p size |
| 1080p240 | 1920 x 1080 | 240 | Compatibility probe; the tested phone rejected 1080p |
| 1080p320 | 1920 x 1080 | 320 | Untested compatibility probe, not successful coverage |
| ultrawide1280x500-dpi160 | 1280 x 720 with 220 px vertical margins | 160 | Effective 1280 x 500 content and side-tile layout |

These are representative compatibility profiles. The 480p160 profile is a useful
starting point for the user's 2023 Hyundai Elantra Hybrid Blue, but its actual
negotiated resolution and density must come from a real car session. None of these
profiles is labeled or asserted to be that car's exact configuration. The larger
and wider profiles also cover possible aftermarket units used with the second phone.

All profiles set `normalizedpi = false`. Screenshot pixels are the projection
evidence; macOS window size is not a scaling measurement. `realdpi` retains DHU's
documented default rather than changing two density inputs at once. The wide
profile keeps the video frame and letterboxing, so a native screenshot can remain
1280 x 720 even though its usable content is 1280 x 500.

For every profile use the same phone, Android Auto version, navigation app version,
app state, fonts/accessibility settings, and actual INI before and after. Record
those versions/settings in the run note or a separate evidence note. Compare
bottom-bar height, navigation search-field height, side-card width, and icon/text
sizes in native pixels and as fractions of usable content dimensions. On a fixed
resolution, a DPI increase should normally increase dp-based element pixel sizes;
adaptive layout thresholds can also change the layout. No universal fixed bar
height is assumed.

Check screenshots for clipped/overlapping elements, usable map area, readable text,
and reachable touch targets. Click the actual targets and verify the intended
action. Dumpsys alone cannot prove that the visual layout or hitboxes are correct.
Recheck the chosen fix after a full phone reboot, two disconnect/reconnect cycles,
and on the brother's phone. The first user-reported Elantra result is positive;
instrumented car display parameters, further real-car scenarios, and voice/audio
checks remain separate. DHU cannot prove the car's display parameters or transport.

`captured-awaiting-review` means only that complete PNG files were received.
`capture-failed` means no complete capture or an interrupted DHU process; inspect
both logs and the phone's current state. A high-DPI negotiation error, black image,
disconnect, UI crash, or reboot is evidence of a failed/unsupported scenario. Never
count it as a smaller-UI success. Stop the matrix and investigate a crash or reboot
before trying another high-DPI profile. Preserve failed run folders.

## Optional read-only phone evidence (outside this harness)

Capture before connection and while each profile is connected:

```text
adb -s SERIAL shell wm help
adb -s SERIAL shell dumpsys display
adb -s SERIAL shell dumpsys window displays
adb -s SERIAL shell dumpsys activity activities
adb -s SERIAL shell dumpsys activity processes
adb -s SERIAL logcat -d -v threadtime
```

Preserve complete dumps before filtering. Identify projection displays by their
owner/name/unique ID and connection lifecycle; display IDs are not stable and must
never be assumed to be `1`. Compare width/height/logical density in DisplayInfo and
the window/activity resource configuration. An expected display density alongside
inflated app resources suggests a vendor per-app override rather than a wrong DHU
configuration. Log tags are Android Auto/firmware-version dependent; broad captures
are safer than relying on a single hard-coded tag.

## Sources

- [Google's DHU setup, console commands, explicit configuration, resolutions and DPI](https://developer.android.com/training/cars/testing/dhu)
- [AOSP window-manager CLI implementation and per-display density selector](https://android.googlesource.com/platform/frameworks/base/+/master/services/core/java/com/android/server/wm/WindowManagerShellCommand.java)
- [AOSP display-density handling](https://android.googlesource.com/platform/frameworks/base/+/bb3fde8af2bcf6910494e68a494253e1e41c34c1/services/core/java/com/android/server/wm/DisplayContent.java)

The platform's `wm density VALUE -d DISPLAY_ID` mechanism operates on displays,
not packages. Vendor app-level resource changes can still bypass it. A temporary
projection display's ID, unique ID, and saved override behavior must be measured
on the actual firmware before treating it as a reusable remedy.
