# Selected-car Bluetooth monitor contract

`BluetoothCarMonitor(Context, Listener)` should receive the foreground service's
long-lived Context. `start()` registers real system events; `close()` unregisters
its receiver/preferences listener, closes profile proxies when permission remains
available, and invalidates pending callbacks. Closing creates no synthetic detach.
All listener callbacks run on the main looper:

```
onCarSignal(boolean connectingOrConnected, String stage, long elapsedRealtimeMillis)
```

The monitor itself never changes DPI. The service/engine owns scheduling,
preparation, expiry, real AA display precedence, and disconnect grace. Only the
explicitly selected bonded CLASSIC/DUAL device can contribute. No scan, location,
pairing, name logging, MAC logging, or arbitrary/test Intent endpoint is used.
Private preferences: file `car-trigger-config`, key `selected_address`.
Service integration owns its separate `automatic_enabled` preference.

It checks Nearby Devices / BLUETOOTH_CONNECT before Bluetooth APIs on Android 12+;
older Android needs normal BLUETOOTH permission. It observes selected-device
HFP/A2DP/adapter CONNECTING and CONNECTED broadcasts plus classic ACL transitions.
LE-only ACL events are ignored. Asynchronous HFP/A2DP profile proxies recover an
already-connected selected car on service startup. Preferences changes reload
selection; permission loss, adapter-off and unpairing withdraw the signal safely.

Signals aggregate to edges, so multiple profile/ACL events do not repeatedly arm
preparation. A physical classic ACL disconnect ends the old epoch and clears stale
profile positives. A late CONNECTED snapshot cannot resurrect it without a fresh
CONNECTING or ACL-connected edge. The engine still owns detach grace; it must not
restore while native AA displays are alive. A proxy service failure alone is not
fabricated as a car disconnect.

Every ten seconds the monitor refreshes selected-device HFP/A2DP state through
public profile APIs and retries unavailable/pending proxies. A genuine positive
connection edge or positive profile snapshot refreshes presence proof, without
duplicating an active listener edge. `isCarActive()` requires that proof within
sixty seconds; unrefreshable cached presence expires and withdraws the hint.
`getLastConfirmedActiveElapsedMillis()` exposes the proof time for service checks.
The service must reconcile fresh `isCarActive()` rather than extending a hold
forever using only its cached listener boolean. An ACL-only desktop connection
without an audio profile naturally loses freshness unless another real positive
event occurs; that bounded bench case must not be labeled real-car profile proof.

`HBAutoPerf` records only the generic stage for emitted real edges. Device IDs
remain in private selection preferences and are not included in timing logs.

Run `sh test/run-car-signal-tests.sh` with Android 34 SDK and JDK 17 configured.
It compiles these two classes against public SDK APIs and runs pure synthetic
signal-state tests. It does not access radios or a phone. Actual receiver delivery,
lead time before AA construction, locked-phone behavior, and real-car timing need
separate device evidence. The kit has desktop Bluetooth/DHU first-frame trials
and a version 11 / 1.1.0 user report of immediately correct scaling on the first
automatic Elantra connection. That report does not instrument native DPI or lead
time, or verify its voice/audio path. A working receiver alone does not prove correct
first-frame scaling for another car's startup timing.
