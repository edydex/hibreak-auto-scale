# Compatibility and known limits

## Phone and receiver evidence

| Target | Evidence |
| --- | --- |
| Bigme HiBreak S, Android 14 / API 34 | Live phone installation, policy readback/restoration, automatic helper and official desktop-head-unit tests |
| 2023 Hyundai Elantra Hybrid Blue, wireless Android Auto | User reported immediate correct automatic scaling on companion 1.1.0; receiver density/timing were not instrumented |
| Companion 1.1.1 / code 12 | Exact-build phone/simulator layout, voice-command execution and full effective-field restoration checks; no new physical-car acceptance claim |
| Another HiBreak / aftermarket receiver | Requires that device's own backup and first-car acceptance; not tested |
| Other Bigme models / different firmware | Not claimed supported; runtime identity/interface guards may refuse writes |

Inspected firmware fingerprint:

```text
Bigme/HiBreak/Smartphone:14/UP1A.231005.007/1756900001:user/dev-keys
```

Guided phone settings use Android's primary user (`0`), the verified Android 14 interfaces, and English UI labels. Unknown screens, other languages and ambiguous controls remain pending. Device/user changes and active or uncertain projection block setup writes. A successful script exit or host test is not proof of a different phone/receiver combination.

## Computer launchers

| Computer | Runtime support and limits |
| --- | --- |
| macOS 11+, Apple Silicon | Private dependency extraction/startup and reuse tested natively; live phone work performed from a Mac |
| macOS 11+, Intel | Pinned runtime provided; native Intel acceptance not yet completed |
| Linux x86_64 with glibc | Pinned Python/ADB provided; native phone/USB-rule acceptance remains separate |
| Linux ARM64 with glibc | Pinned Python provided; install your distribution's ADB first because Google's Linux archive is x86_64 |
| Alpine / musl Linux | Use distribution Python and ADB; portable Python requires glibc 2.17+ |
| Windows 10/11 AMD64 or ARM64, PowerShell 5.1+ | Portable runtimes provided; native Windows USB/driver and PowerShell 5.1 acceptance remain separate |

Linux also needs Bash and ordinary download/archive tools; preparing downloads uses curl, tar, awk, a SHA-256 tool and flock. The Windows launcher changes execution policy only for its process; it does not change user/machine policy or override managed Group Policy. Standard accessory approval, Linux USB permissions and Windows Android drivers remain operating-system steps.

See [verification](verification.md) for actual checks. Host tests and CI do not establish a successful car installation.

## Resolution and density

The helper learns authoritative Android Auto-owned native main-display density; it does not derive it from resolution or app-generated virtual displays. Different receivers can legitimately use different densities at the same resolution.

Representative desktop-head-unit profiles inspected on the phone:

- 800 × 480 at 160 DPI: inflated baseline and corrected rendering.
- 1280 × 720 at 160, 240 and 320 DPI: projected/native density reviewed.
- 1280 × 500 usable content at 160 DPI, carried in a 1280 × 720 transport with margins.
- 1920 × 1080 at 240 DPI: **rejected by the phone encoder**; it reported a 1920 × 1072 maximum. A supplied 1080p profile is a probe, not successful coverage.

Mixed authoritative main/cluster densities cannot be represented by this firmware's single per-app setting and are refused. Unknown, conflicting, inactive or out-of-range display information causes no new writes.

## Operational limits

- Android Auto constructs some containers when projection starts. If advance preparation misses that moment, live density correction can require a reconnect. Automatic success depends on the chosen car's genuine Bluetooth signal arriving in time.
- The app holds prepared density while the selected Bluetooth car remains connected, even when projection is absent. Android Auto, Maps and Google can therefore look smaller on the phone temporarily.
- Bigme's Recents padlock is required separately from Android's battery-idle exemption. Force-stop, storage clearing and vendor task killing can prevent automatic operation.
- Firmware/schema drift intentionally pauses writes; restore before an OTA. Original effective values can restore without deleting a vendor row created by a write.
- Assistant configuration readback and simulator recognition do not establish the car's physical microphone, steering-wheel button, mobile-data route or speaker audio.
- Short idle/simulator observations do not establish long-term background survival, navigation frame rate or battery-life gains.
- [Related halo/text-enhancement research](https://github.com/joemk88/hibreak-android-auto-fix) addresses a different symptom. Its permanent enhancement change is not part of default setup here.
