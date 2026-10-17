# Authoritative native density parser

`HostDensity.parse(String dump)` returns `connected`, `dpi`, nullable `error`,
`anyAaOwned`, and an immutable list of `Surface` objects (`name`, `dpi`, `kind`,
`state`). `safeToApply()` requires an active authoritative host, no uncertainty,
and a native density within 72 through 640.

Only displays actually owned by `com.google.android.projection.gearhead`, named
exactly `GhFacetBar` or `Dashboard`, with state `ON`, can choose a main-screen DPI.
All authoritative entries must agree. AA-owned cluster-like names add conflict
guards, including inactive clusters, but never select the main density alone.
Ghost activities, CarAppService, template, component/app-drawn names, and unknown
surfaces cannot choose the host DPI. Owner/density/state properties are parsed
outside quotes and nested structures; a virtual-display name cannot spoof them.

Never treat every `connected == false` as a disconnect. A certain disconnect
requires `!connected && error == null && !anyAaOwned`. Unknown, inactive, or only
app-generated AA surfaces can represent negotiation or teardown; they produce an
uncertain result that must preserve policy. `hasAnyAaDisplay(String)` also exposes
the ownership guard for refusing an initial disconnected-state backup.

The test runner only compiles local Java and parses synthetic strings or a saved
display dump. It never accesses a phone. Run it with a configured JDK:

```sh
sh test/run-host-density-tests.sh
# Optional extra checks against your own private saved dump:
# sh test/run-host-density-tests.sh /private/local/display-dump.txt
```

The kit includes no private phone display fixture. Default tests are synthetic.
