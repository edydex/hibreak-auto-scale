# Setup

## Get the complete release

Download **HiBreak-Auto-Scale-Setup-v1.1.1-beta.1.zip** from [Releases](https://github.com/edydex/hibreak-auto-scale/releases/tag/v1.1.1-beta.1). Extract every file into one folder before launching it. The standalone APK is also provided for manual installation, but tapping it alone cannot grant the one-time ADB diagnostic permission or configure the computer-assisted steps.

The release's `SHA256SUMS` and `release.json` record the distributed files and APK identity. They detect accidental changes; they are not a substitute for trusting the release publisher. The APK's signing certificate fingerprint is recorded in [verification](verification.md).

## Connect and run

1. Disconnect Android Auto and unlock the phone. Enable Developer options, then **USB debugging**. Use a cable that supports data.
2. Connect the phone. Accept **Allow USB debugging?** on the phone and any normal accessory approval on the computer.
3. Start the launcher from the extracted folder:

   | OS | Start |
   | --- | --- |
   | Mac | Double-click `Setup-on-Mac.command` |
   | Linux | `bash Setup-on-Linux.sh` |
   | Windows | Double-click `Setup-on-Windows.cmd` |

Missing Python and ADB are downloaded to a private user folder, verified against pinned SHA-256 values, and reused. The first Google tools download asks you to review and accept the included SDK terms. Existing compatible tools are reused. The launchers do not install packages globally, change PATH or request administrator access. The wizard waits for phone authorization; it does not need restarting immediately while you accept the prompt.

Mac may require its normal first-open approval. Linux USB rules and Windows device drivers can require distribution/vendor installation outside this wizard. Do not run the whole wizard as root. Linux ARM64 needs a working distribution-provided ADB. See [computer compatibility](compatibility.md).

## Complete the phone steps

The wizard captures this disconnected phone's original display-policy backup before making changes. If an existing companion might still own car settings, it first requires a verified **Stop and restore** state. Do not clear storage to bypass this check.

The remaining personal choices are:

- **Bigme background lock:** open Recents → Process manage and padlock **HiBreak Auto Scale**. The wizard notices the vendor readback. Android's battery-idle exemption is separate. Clear All preserves the padlock on the tested firmware; individually swiping the helper away removes it.
- **Car:** choose the actual already-paired car in **Automatic for paired car**. Setup configures and checks Nearby devices access for this helper; it does not scan, pair a car or guess which device is yours. Pair the car normally first if necessary.
- **Assistant:** if a different assistant is already selected, choose whether to replace it with Google. First-run Google consent and onboarding still require you. Settings readback is not a microphone/audio test.

Unknown, ambiguous or translated UI labels leave their affected steps pending. Review the summary rather than assuming every setting succeeded. The summary distinguishes **verified**, **pending**, and optional **user-confirmed** car checks. Exit code `2` means a remaining checklist, `1` means blocked, and `130` means interrupted.

## First connection, while parked

1. Connect normally and let the helper learn the receiver's native display density. It does not copy the simulator's 160-DPI profile. If the initial controls remain large, wait for adjustment and disconnect/reconnect within ten seconds so Android Auto recreates them.
2. For a flat map, open **projected Maps → Settings → Raised Buildings** and switch it off. This is separate from the phone Maps preference configured by setup.
3. Test a steering-wheel or on-screen voice request, an audible response, and call audio. This checks the physical car path that a simulator cannot establish.
4. Disconnect both Android Auto and the selected car connection. Allow the restore grace, then check that normal phone app sizing returns.
5. Check a later ordinary connection without opening the helper or pressing Prepare. **Prepare for car** remains a fallback: while disconnected, wait for **Ready**, then connect within ten minutes.

Turn USB/wireless debugging off after setup if you no longer need it. Setup does not change debugging or sleep settings.

## Choose apps or update only

Default optional launcher choices are **Maps, Messages, Reminder, Heritage and NewPipe**. Protected built-in Phone/Settings/Exit/Maps controls remain where Android Auto requires them. Reminder is an Assistant shortcut, not a separate phone app. Hiding icons does not uninstall apps or establish a performance gain.

Arguments can follow any setup launcher. For example, from the kit folder:

```sh
bash Setup-on-Linux.sh --keep-app Maps --keep-app Messages
./Setup-on-Mac.command --serial PHONE_SERIAL
```

Any `--keep-app` arguments replace the entire default keep list. Use exact visible labels; missing requested apps are reported pending. The wizard does not download phone apps. Some apps appear only on the actual receiver, so check that launcher too.

Use `--install-only` with an OS launcher for an APK update without repeating preference setup. It preserves application data and stops on a signing/version mismatch. Never uninstall or clear an active recovery state to bypass that error. To repeat full configuration, first disconnect and complete **Stop and restore**.

Other options:

- `--check-car-now`: offer the optional car checklist immediately.
- `--non-interactive`: leave required personal choices pending.
- `--wait-seconds 0`: check the connection immediately.
- `--state-dir PATH`: choose a private report/backup directory.
- All launchers: `--check-dependencies` tests only computer tools; `--accept-tool-licenses` explicitly accepts the supplied SDK terms for an intentional automated run.

## Private records and troubleshooting

Default private records:

| Computer | Folder |
| --- | --- |
| Mac | `~/Library/Application Support/HiBreak Auto Scale/runtime/setup-records` |
| Linux | `${XDG_CACHE_HOME:-~/.cache}/hibreak-auto-scale/runtime/setup-records` |
| Windows | `%LOCALAPPDATA%\HiBreakAutoScale\setup-records` |

Keep these records until restoration succeeds. They contain this phone's identity and original policies and can contain account/UI content. Do not upload them to public issues or apply their backup to another phone.

If no phone appears, check that it is unlocked, USB debugging is enabled, the cable supports data, and its authorization prompt was accepted. A charging notification alone does not prove a data connection. If several physical phones are connected, disconnect the others or pass `--serial`; the tool refuses to guess.

If setup stops after changes, keep the report and backup. It deliberately does not clear data or perform a broad automatic rollback. Review what verified and what remains pending. [Undo and recovery](undo.md) explain the safe next steps.
