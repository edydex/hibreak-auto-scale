# Third-party components and attribution

The project's original source, host test stand-ins, scripts and documentation
use the [MIT license](LICENSE). That license does not replace the terms of
downloaded software or Android/vendor interfaces.

| Component | Use and terms |
|---|---|
| Google Android SDK Platform-Tools / ADB | Downloaded from Google's versioned archives when needed. The installer verifies the archive hash, retains `NOTICE.txt` and asks for the included [Android SDK terms](ANDROID-SDK-LICENSE.txt) before a new ADB download. [Official tools](https://developer.android.com/tools/releases/platform-tools). |
| CPython / Python Software Foundation | Downloaded as a private runtime when needed; its license and component notices remain in the extracted runtime. Windows uses Python's official embeddable ZIP. [Python license](https://docs.python.org/3/license.html). |
| Astral python-build-standalone | Supplies the pinned Mac/Linux portable CPython builds. Runtime licenses/notices remain in the extracted files. [Project](https://github.com/astral-sh/python-build-standalone), [running the distributions](https://docs.astral.sh/python-build-standalone/running/). |
| Android SDK build platform/tools | Used for optional source compilation and CI; the SDK itself is not bundled in the release ZIP. Developers accept its terms through their own installation. |
| Bigme firmware APIs | The bridge discovers the installed device's interface at runtime. No proprietary firmware or decompiled vendor implementation is distributed. |

`runtime-downloads.json` records the exact dependency URLs and SHA-256 values.
No Python or ADB runtime binaries are committed to this repository or bundled
inside the setup ZIP. The root APK and bridge JAR contain this project's code;
the APK's embedded bridge matches the separately shipped bridge.

The related [joemk88/hibreak-android-auto-fix](https://github.com/joemk88/hibreak-android-auto-fix)
investigation describes text-enhancement halos, a separate issue from density.
It is credited as related research; its implementation was not copied. The
automatic helper preserves text enhancement. See [compatibility](docs/compatibility.md)
for the distinction and test boundary.
