# Display-policy diagnostics and explicit setters

This small Java program can run through Android's `app_process` as the ADB shell
user, or as the unchanged normal app UID when bundled by the companion. Inspection
requires no setting changes; its explicit setters do change the selected policy.
The ADB shell path needs no APK or root. The companion separately requires its
documented diagnostic grant.
It uses the phone's own vendor framework classes and Binder stub; no Binder
transaction IDs or vendor parcel layout are assumed.

`./build.sh` compiles against the local Android 34 SDK with JDK 17, then builds
`build/display-policy-bridge.jar` with D8. `BRIDGE_JAVA_HOME`, `ANDROID_SDK_ROOT`,
`BRIDGE_ANDROID_JAR`, and `BRIDGE_D8` can override tool paths. Building does not
connect to a phone or install anything.

`./test-host.sh` runs reflection/write-verification checks against host-only fake
policies and interfaces. These check each mapped field, unchanged before snapshots,
false setter returns (including a setter that nevertheless changes state), ignored
writes, null pre-policy, and getter/setter signature drift. Test classes and JSON
stand-ins remain outside the Android DEX and are not device acceptance evidence.

After the operator has selected and verified the intended ADB serial, an example
manual run is:

```sh
adb -s SERIAL push build/display-policy-bridge.jar /data/local/tmp/display-policy-bridge.jar
adb -s SERIAL shell 'CLASSPATH=/data/local/tmp/display-policy-bridge.jar app_process /system/bin DisplayPolicyBridge inspect'
adb -s SERIAL shell 'CLASSPATH=/data/local/tmp/display-policy-bridge.jar app_process /system/bin DisplayPolicyBridge get com.google.android.projection.gearhead'
```

The `inspect` command (also the default) emits one JSON object describing build,
UID, interface and stub methods, field schemas, transaction constants, descriptor,
Binder state, proxy methods, and matching getter schemas. It invokes only Binder
discovery, descriptor, liveness, ping, and the generated `Stub.asInterface`.
It does not call policy methods.

`serve` starts a same-UID private stdin/stdout JSON-lines loop. It first emits a
`ready` response with UID and protocol version, then accepts only `inspect`,
`get`, `set-dpi`, `set-dpi-enabled`, and `set-text-enhance`. Request fields are
`command`, `package` where needed, and integer `value` for setters; unknown fields
and commands are rejected. One bad request produces an error JSON response and
does not exit the loop. EOF ends the helper. It opens no socket or network port.
The Binder proxy is reused while alive. Full class/schema metadata is generated
only for inspect; get/set retain method identity and all policy/readback fields
without repeatedly serializing the full interface. CLI commands preserve their
existing exit-code behavior.

The optional read-only `get PACKAGE` command invokes the first discovered allowlisted
single-String, non-void policy getter in this explicit order:

1. `getPolicyByPackage`
2. `getDisplayPolicyForPackage`
3. `getPackageDisplayPolicy`
4. `getDisplayPolicyByPackage`
5. `getDisplayPolicy`
6. `getPackagePolicy`

It outputs the exact selected method and a bounded reflection dump of the return
value. It never selects methods solely because their name begins with `get`.

Three narrow write commands are available after confirming the current firmware's
interface and setter semantics:

| Command | Accepted integer | Exact interface setter | Readback field |
| --- | --- | --- | --- |
| `set-dpi PACKAGE INTEGER` | 0 to 1000 | `setDpiForPackage(String,int)` | `appDpi` |
| `set-dpi-enabled PACKAGE INTEGER` | 0 or 1 | `setIsDpiSettingForPackage(String,int)` | `isDpiSetting` |
| `set-text-enhance PACKAGE INTEGER` | 0 to 100 | `setTextEnhanceForPackage(String,int)` | `appTextEnhance` |

Each command requires the exact primitive-boolean setter return type and exact
`getPolicyByPackage(String): xrz.framework.manager.DisplayPolicy` getter. It
finds and validates the named instance-int readback field on the runtime object
before attempting a mutation. Output includes `readOnly: false`, the exact
methods, complete bounded before/after policy snapshots, the setter's boolean
return value, and explicit value verification. A false result, readback mismatch,
or any exception produces a nonzero exit code. `mutationAttempted` distinguishes
precondition failure from a write that may have occurred. There is no automatic
rollback. Commands change one field each; enabling DPI does not also select a DPI.
Zero DPI is accepted for controlled research and restoration; its actual vendor
semantics must be confirmed before use. These input bounds are tool limits, not a
claim that every value is suitable for everyday use.

There are no arbitrary invocation commands or raw `transact` calls. This tool
does not restart apps, alter global density, grant permissions, or combine changes.

Limits: vendor classes may be outside the boot class path; hidden-API enforcement,
SELinux, or Binder permission checks may prevent access. A matching getter's
read-only semantics must still be confirmed from the vendor implementation;
the naming allowlist is not a proof of implementation behavior. Reflection
cannot explain a field's units or persistence by itself. Returned objects are
limited to five levels and 64 fields/items, with repeated-reference markers.
Accessors and `toString()` are never invoked on returned vendor objects. No
device runtime success is claimed by a successful host compilation. A successful
setter readback alone does not prove the resulting Android Auto layout, persistence
across reboot, or restoration behavior; those require separate device tests.
