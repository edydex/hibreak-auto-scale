# Performance notes

## What changed in the helper
The released companion is 1.1.1 / code 12, signed with the existing key. It skips
unchanged idle-state saves, unchanged service-notification reposts, and identical
visible status redraws. Backup capture, every journal commit, ownership checks,
database reload/readback, restoration, display polling, and Bluetooth timing are
unchanged. Explicit Refresh, re-enabling and app resume can publish the current
notification again after its category is unhidden.

The previous version repeatedly saved 510,256 bytes roughly every 30.2 seconds
while idle. In a measured 30-second settled idle window, version 1.1.1 continued
its display check and made zero unchanged state saves. This verifies removal of
duplicate storage/serialization work. Necessary state changes still save, and
every settings-write safeguard remains in place.

No defensible whole-device CPU or battery-percentage gain was established. This
is modest waste reduction, not a measured navigation frame-rate improvement.

## Maps visual settings
Two independent settings were changed from on to off:
- On the phone: Maps > Navigation > Show raised buildings.
- In projected Android Auto Maps: Settings > Raised Buildings.

Changing the phone setting alone initially left buildings raised in Android Auto.
The projected setting was then changed too, and the projected map showed flat
outlines instead of extruded buildings. Satellite view was already off; it was
not an additional optimization made here. Routing, traffic-aware guidance and
alerts remain available. Turn the same two switches back on to restore building
detail. These are Maps preferences, not values installed or restored by the helper.

## Launcher and music preferences
Android Auto > Customize launcher was used to hide unwanted optional entries.
The observed launcher choice kept Maps, Messages, Reminder, Heritage and NewPipe. The guided installer uses the same default keep list; users can replace it.
The actual projected launcher showed Exit, Heritage, Maps, Messages, NewPipe,
Phone, Reminder and Settings. Reminder is Android Auto's built-in Assistant
action that submits "Set a reminder", not a separately
installed app. Phone, Settings, Exit and Maps are protected built-in entries on
this build. Optional launcher entries were hidden through Android Auto settings;
their apps were not disabled or uninstalled.

Start music automatically was switched off and its unchecked UI state verified.
Manual playback is still available. To undo these preferences, recheck desired
launcher entries or turn automatic music back on. Another phone can choose its
own optional launcher entries; the listed five are this user's preference.
Hiding icons does not establish that their background work stops or that CPU
usage decreases. The helper's Stop and restore does not reset these preferences.

## Voice function preserved
Google remains the default assistant with microphone access while in use. Button
and screen-microphone activation remain the intended path. Hey Google was already
off, disabled/unavailable on this phone; no wake-word change or saving is claimed.

With version 1.1.1 installed, a known recorded request, "Search for gas stations
in Seattle", was sent through the official Desktop Head Unit microphone path.
The request was recognized and the matching Seattle gas-station results appeared
in projected Maps. The final short check after launcher pruning had no reported
DHU decoder errors. This confirms that this voice command still functions after
the update. It does not prove the Elantra's physical microphone, steering-wheel
button timing, mobile-data route, or an audible response through car speakers.

## Why there is no cpu/battery gain number
The first sample after changing only the phone navigation setting still rendered
raised buildings in Android Auto and showed no clear overall CPU reduction.
It is not an optimized flat-map result. A later nominal final sample displayed
the Android Auto launcher rather than Maps. Another flat-map sample overlapped
voice activity. Those windows are excluded from before/after gain claims.
There was no clean, matching-scene final benchmark.

CPU snapshots varied with scene, voice processing, tile/cache activity and other
phone work. A process showing 100% in Android top represents one occupied core,
not all eight cores of this phone. The measurement tools add some work too.
Short stationary simulator observations cannot establish drive-long battery life.

For a reusable comparison, use the same phone/build, head-unit resolution/FPS,
Maps position/zoom/camera and layer settings, network state, power conditions and
similar temperature. Let tiles settle, pause the helper UI, avoid voice/menu input,
and collect comparable windows. Keep unrelated settings and installed apps intact.
No blanket app disabling, data clearing, forced GPU/overlay settings, process
limits, CPU-governor changes, or broad battery restrictions were used here.

## Real-car boundary and undo
The user's successful first automatic Elantra connection was on version 1.1.0.
Version 1.1.1 has current phone/DHU checks; a new physical-car test is separate.
The car's negotiated display profile was not changed by these simulator trials.

Stop and restore returns the helper's still-owned DPI/flag fields to this phone's
saved values. Keep the saved backup and recovery data until restoration succeeds.
Maps layers, launcher choices, automatic music and Google assistant/microphone
settings are separate; undo them through their respective settings only if wanted.
Each additional phone needs its own backup, paired-car selection and setup.

[Supported Maps navigation controls](https://support.google.com/maps/answer/3273406?hl=en).
