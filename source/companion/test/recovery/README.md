# Production recovery fault checks

`JAVA_HOME=/path/to/jdk17 sh run.sh /path/to/repository` compiles the repository's
unchanged `ScaleEngine.java`, `HostDensity.java` and `PreparationWindow.java`.
The Android SDK, a phone, network access and third-party libraries are unnecessary.

The host-only dependencies supply synthetic Android context/clock, JSON values,
separate vendor cache/database policies, durable state snapshots, and injected
failures. The bridge asserts a matching durable transaction intent exists before
every synthetic vendor setter. Tests call the real public enable/tick/stop paths;
single-write fault cases invoke the real private `change()` through reflection
to place failures precisely without duplicating the transaction implementation.
Process restart means constructing a fresh production engine from the last
successfully committed independent state snapshot.

The tests establish production journal ordering, outcome classification,
full-policy readback checks, conflict preservation and restore decisions under
the specified faults. They do not establish Android AtomicFile durability, actual
vendor SQLite/cache behavior, framework process death, Bluetooth timing, display
negotiation, USB authorization, or physical car behavior. JSON/Android/bridge/store
stand-ins belong only to this host test input; never include them in APK sources.
