# Undo and recovery

## Stop scaling safely

1. Disconnect Android Auto and the selected Bluetooth car.
2. Open **HiBreak Auto Scale → Stop and restore**.
3. Wait for its successful off/restored status. Preserve the saved backup and any warning if it reports a conflict or needs attention.
4. Only after successful restoration, remove the helper if desired. You can also remove its Bigme Recents padlock, battery-idle exemption and granted permissions.

**Do not uninstall, clear storage, force an older APK over it, or revoke DUMP while restoration is pending.** Its private state contains the original settings and any interrupted-write journal. Keep that recovery state intact.

Automatic restoration normally occurs after both projection and the selected car connection end, following the display grace. Bluetooth loss alone must not restore app density while Android Auto is still projecting. **Stop and restore** deliberately disables automatic monitoring and car arming as well as requesting restoration.

## What restores

The companion restores only its still-owned `appDpi` and `isDpiSetting` fields for Android Auto, Maps and Google. It preserves unrelated fields and reports external edits instead of silently overwriting them. If setting a value created a previously absent vendor row, the original effective values can restore while the row remains: this firmware exposes no supported row-deletion operation.

The optional advanced CLI also supports its backed-up `appTextEnhance` field. Normal automatic scaling and guided setup do not permanently disable text enhancement.

Each phone needs its own backup. Recovery verifies hardware identity, firmware and runtime interface; another phone's settings are not a valid recovery source.

## Undo other setup preferences

These are separate from the companion's density backup. Use the original values in your private setup report/change journal if you want to return them too:

| Setting | Where to change it |
| --- | --- |
| Hidden car apps | Android Auto settings → Customize launcher; check the entries you want |
| Automatic music | Android Auto settings → Start music automatically |
| Phone 3D buildings | Phone Maps → Settings → Navigation → Show raised buildings |
| Projected 3D buildings | Android Auto Maps → Settings → Raised Buildings |
| Default assistant | Android settings → Apps → Default apps → Digital assistant |
| Microphone access | App info → Permissions for Google / Android Auto |
| Helper notification | Helper App info → Notifications → Automatic Android Auto scaling; then open the helper or tap Refresh status |
| Bigme padlock | Recents → Process manage; unlock the helper only after restoration |
| Helper battery exemption | Android battery optimization settings; remove only its exemption if setup added it |

Changing Android's assistant role can cause Android-managed permission changes. Review the report's recorded deltas before reversing permissions; do not indiscriminately revoke Google's permissions or reset all AppOps. A working voice setup can be preserved while removing the scaling helper.

The install audit includes permission/exemption undo commands only for grants that installer added. Run them only after restoration, against the original identified phone. The full wizard also records additional preference changes. There is no broad unattended “reset everything” command.

## Firmware updates and interrupted operations

**Complete Stop and restore before a phone firmware update.** Firmware or interface changes pause writes, including restoration, rather than assuming that old recovery data remains valid. This is a firmware-dependent tool; maintenance after an OTA can be necessary.

If an update already occurred while car density was owned, preserve the app data and exported backup. Do not change the saved fingerprint/schema or force another phone's backup through the checks. Collect a sanitized description of the old/new firmware and current status for review.

If setup or an app write was interrupted, keep both the computer's report and the companion's state. The app journals each attempted field write before it occurs and resolves a pending transaction through persisted-policy reload/readback when it resumes. Host tests do not prove every possible power-loss path; do not treat an unverified interrupted operation as restored. Opening the app and refreshing can resume recovery after a force-stop or vendor task kill.

**Export saved backup** saves a complete committed snapshot through Android's file picker. Keep it private. Exporting does not change policies or import settings.

## Remove downloaded computer tools

The launchers install no global Python/ADB and make no PATH changes. Private runtimes can be removed after setup:

- Mac: `~/Library/Application Support/HiBreak Auto Scale/runtime/`
- Linux: `${XDG_CACHE_HOME:-~/.cache}/hibreak-auto-scale/runtime/`
- Windows tools: `%LOCALAPPDATA%\HiBreakAutoScale\tools\`

**Save the private `setup-records` folder first**, especially when deleting a parent runtime folder. Windows records are alongside `tools`, under `%LOCALAPPDATA%\HiBreakAutoScale\setup-records`. Deleting computer runtimes does not restore phone settings.

Setup does not change the phone's sleep settings or automatically turn debugging off. Disable USB/wireless debugging yourself when finished if you no longer need it.
