# Manual display-policy CLI

## Advanced policy tool

`hibreak_aa.py` is a Python standard-library CLI for the vendor app-display policies
of Android Auto, Google Maps, and the Google app on a Bigme HiBreak. It uses ADB and
`display-policy-bridge.jar`, which discovers the phone's own vendor interface by
reflection. No Binder transaction numbers or parcel layout are built into Python.

Place the bridge JAR beside the Python file when distributing the toolkit. During
development it also finds `../bridge/build/display-policy-bridge.jar`. ADB can be
on PATH, supplied with `--adb`, or placed in `platform-tools/adb` beside the script
or its parent directory. The helper is copied to a content-addressed JAR file in
the selected phone's `/data/local/tmp`; it does not install an APK or require root.

All options before the command select the device/tool locations. Use an explicit
ADB serial, particularly when another family member's phone is also connected:

Before a manual `apply` or `restore`, choose **Stop and restore** in the automatic
companion and wait for its successful restore status. Keep automatic monitoring
off while the CLI changes preferences, so two controllers do not compete.

```sh
python3 hibreak_aa.py --serial SERIAL status
python3 hibreak_aa.py --serial SERIAL backup --output original-phone.json
python3 hibreak_aa.py --serial SERIAL apply --dpi 160
python3 hibreak_aa.py --serial SERIAL restore original-phone.json
```

`160` is an example of an explicit profile choice, not an automatically determined
value for a particular car. Choose and test the appropriate value against the
actual head unit. The CLI reads no historical logs and never guesses DPI from an
old projection session. Accepted apply DPI is 72 through 640. An optional
`--text-enhance 0..100` is available only when deliberately requested; otherwise
that field stays unchanged.

By default only the three supported apps that are actually installed are included.
Use repeated `--package` options after `status`, `backup`, or `apply` to select a
subset. An explicit package must be installed and must be one of:

- `com.google.android.projection.gearhead`
- `com.google.android.apps.maps`
- `com.google.android.googlequicksearchbox`

If `--serial` is omitted, the CLI proceeds only when authorized ADB transports all
resolve to one nonempty hardware serial. USB and wireless transports for that same
phone can coexist. Multiple physical phones, unidentifiable transports, a different
manufacturer, or a model other than HiBreak cause refusal. The device's hardware
serial, manufacturer, model, SDK, fingerprint, and initial density are verified
before writes. All remote commands explicitly use the chosen ADB serial.

## Backups and operation records

The CLI saves local files in `records/` beside the script unless `--state-dir` is
given. Every command creates an audit JSON. `backup` stores exact reflected policy
fields, original row presence, matching service-dump rows and the original dump,
device identity/build, runtime method/field schema, helper hash, and app versions.
The phone's actual original values are captured independently for each phone.
No policy defaults are invented; every phone must create its own backup.
Raw saved rows and effective policy values are separate records: the vendor getter
resolves several color-mode defaults, so unrelated raw values can legitimately
differ from their effective values. DPI, its enabled flag, and text enhancement
must agree between raw and effective records; a discrepancy requires investigation
of global overrides before applying a profile.

`apply` and `restore` atomically save a new backup before their first app-policy
write. The backup path is persisted in the audit before mutation. Existing backup
files are never overwritten. Each setter records its exact before/after policy
and an independent readback. Unrelated fields are preserved and unexpected field
changes or concurrent policy changes stop the operation. No-op values are skipped.
An actual change requires a true setter result and exact readback. Final checks
reload the persisted service policy list and read the effective policy afterward,
so a failed DB insert cannot pass using only temporary in-memory values. Changed
packages must have persisted rows; existing rows retain their unrelated raw fields.

`apply --dpi N` enables the DPI flag when necessary and sets app DPI. `restore`
restores only the original `appDpi`, `isDpiSetting`, and `appTextEnhance` values.
It preserves any current changes to other fields rather than overwriting them
with an old full-row snapshot. Restore requires the same hardware identity,
firmware fingerprint, and runtime schema as its original backup.
Apply also requires every selected app's current `appDpiScale` to equal 1, because
the inspected vendor resource and display services handle a nonunit scale
inconsistently. Restore preserves any preexisting scale value.

The inspected firmware sets the flag in memory but skips persistence/notification
when app DPI equals `DatabaseHelper.INIT_DPI`, which is initialized from
`ro.sf.lcd_density`. Before a necessary flag change in that state, the CLI stages a
different supported DPI, applies the flag, and then writes the exact final DPI.
Every stage is in the audit and the pre-operation backup remains available if a
stage fails. The original value may be outside the apply range; restore accepts
the exact backed-up bridge-supported DPI range of 0 through 1000.

The exposed vendor setters do not remove policy rows. A package that originally
had no saved row can retain a new row after its original values are restored.
The CLI reports `restored-values-row-presence-differs` with exit code 3 in that
case and lists the affected packages. It does not claim exact storage rollback.

If any step fails after a setter was attempted, the result is `partial-failure`,
with the backup and audit paths. Automatic rollback is not attempted, because it
could obscure a failed write or overwrite a concurrent adjustment. Preserve those
files; use a reviewed restore after inspecting the failure.

## What the result verifies

`applied-fields` or `restored-fields` confirms exact live policy readback and no
observed collateral changes during the operation. It does not establish the
Android Auto layout or persistence across a phone reboot. Reconnect projection,
inspect its native screenshots and touch targets, and verify persistence after
reboot separately. Application restarts and physical car acceptance are separate
operator steps; this CLI never force-stops apps or changes global display density.

The host-only tests use fake transports/policies and do not contact a phone:

```sh
python3 -m unittest discover -s tests -v
```

