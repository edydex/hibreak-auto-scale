# Contributing

Read [development](docs/development.md), [compatibility](docs/compatibility.md)
and [verification](docs/verification.md) before changing device behavior.

Keep phone-specific backups, reports, UI captures, SDKs and signing material
outside the repository. Synthetic fixtures are preferred. A raw `probe.json`,
setup report or display dump can expose a device ID, Bluetooth address, account,
location or screen content; do not attach one to a public issue or pull request.

For a bug report, include only the model, firmware/build version, Android Auto
version, head-unit model, connection type and reproduction steps. Remove personal
names, addresses, coordinates, account data and hardware serials from excerpts.
Describe expected/actual behavior and whether Stop and restore succeeds.

Changes to settings writes must retain own-phone backup, durable pre-write
journaling, runtime schema/identity validation, exact persistence/readback checks,
ownership-aware restore and preservation of unrelated fields. Do not replace
those contracts with hardcoded Binder transaction IDs or guessed defaults.

Run the host checks and Android compile/Java checks described in the development
guide. Host and CI success is not physical-phone/head-unit acceptance; report
that boundary in the pull request. Keep a known original backup until restoration
succeeds. Do not experiment with fault injection on a phone used for driving.

Do not publish a locally signed compile-test APK as an update to the release APK.
Only the original release signer can preserve update compatibility. Build output,
keys and passwords stay private. Dependency pins and release metadata changes
need matching checksum/manifest validation and current official-source review.
