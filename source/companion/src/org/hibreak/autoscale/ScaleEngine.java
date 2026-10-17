package org.hibreak.autoscale;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.IOException;
import java.util.*;
import java.util.regex.*;

/** One worker owns this engine. Every write has a durable before/intent record. */
final class ScaleEngine {
    private static final Pattern POLICY_ROW_PATTERN = Pattern.compile("DisplayPolicy\\{([^{}]*)\\}");
    private static final Pattern INTEGER_VALUE_PATTERN = Pattern.compile("-?\\d+");
    private static final Pattern DECIMAL_VALUE_PATTERN = Pattern.compile("-?\\d+\\.\\d+");
    private final Context context;
    private final StateStore store;
    private final BridgeClient bridge;
    private JSONObject state;
    private boolean validated;
    private boolean firstTick = true;
    private long absentSince = -1;
    private boolean connected;
    private boolean automaticCarActive;
    private final String processToken = UUID.randomUUID().toString();
    ScaleEngine(Context context) throws Exception { this.context = context; store = new StateStore(context); bridge = new BridgeClient(context); state = store.load(); }
    boolean enabled() { return state.optBoolean("enabled"); }
    boolean connected() { return connected || (absentSince >= 0 && state.optJSONObject("owned") != null && state.optJSONObject("owned").length() > 0); }
    boolean needsWork() { return StateStore.workNeeded(state); }
    String status() { return state.optString("status", "Waiting for status."); }
    void close() { bridge.close(); }
    void setAutomaticCarActive(boolean active) { automaticCarActive = active; }

    void enableAutomaticMode() throws Exception {
        requireDump();
        if (!state.has("backup")) { enable(); return; }
        validate(); recoverPending();
        state.put("sessionActive", true).put("enabled", true);
        setStatus("Automatic paired-car detection is enabled. Waiting for the selected car.");
        store.save(state);
    }

    void prepareAutomaticallyIfIdle() throws Exception {
        if (!automaticCarActive) return;
        HostDensity.Result host = HostDensity.parse(bridge.displayDump());
        if (host.anyAaOwned || host.connected) return; // Never restart or prepare over a live projection.
        if (host.error != null) { setStatus("Car connection detected. Waiting for reliable display information before preparation."); return; }
        if (state.optInt("lastHostDpi", 0) < 72 || state.optInt("lastHostDpi", 0) > 640) {
            setStatus("Car connection detected. Connect Android Auto once to learn its DPI; the first unprepared connection may need a quick reconnect.");
            return;
        }
        prepareForCar(true);
    }

    void prepareForCar() throws Exception {
        prepareForCar(false);
    }
    private void prepareForCar(boolean automatic) throws Exception {
        long started = SystemClock.elapsedRealtime();
        boolean completed = false;
        android.util.Log.i("HBAutoPerf", "prepare-start");
        try { prepareForCarInternal(automatic); completed = true; }
        finally {
            JSONObject preparation = state.optJSONObject("preparation");
            android.util.Log.i("HBAutoPerf", "prepare-complete durationMs=" + (SystemClock.elapsedRealtime() - started)
                    + " completed=" + completed + " phase=" + (preparation == null ? "none" : preparation.optString("phase")));
        }
    }
    private void prepareForCarInternal(boolean automatic) throws Exception {
        requireDump();
        if (!state.has("backup")) throw new IOException("Learn this car first: enable monitoring, connect once, and wait for its DPI to be saved.");
        setStatus("Checking saved phone settings. Wait for Ready before connecting Android Auto.");
        validate(); recoverPending();
        HostDensity.Result host = HostDensity.parse(bridge.displayDump());
        if (host.anyAaOwned || host.connected || host.error != null) throw new IOException("Disconnect Android Auto before preparing. Wait for Ready before connecting again.");
        int dpi = state.optInt("lastHostDpi", 0);
        if (dpi < 72 || dpi > 640) throw new IOException("No learned car DPI yet. Enable monitoring and connect once to learn this car.");
        JSONObject packages = state.getJSONObject("backup").getJSONObject("packages"), preflight = new JSONObject();
        for (String pkg : BridgeClient.PACKAGES) {
            if (!packages.has(pkg)) continue;
            try { context.getPackageManager().getPackageInfo(pkg, 0); }
            catch (PackageManager.NameNotFoundException absent) { continue; }
            JSONObject current = bridge.get(pkg); validatePolicy(current); assertOwnershipForApply(pkg, current); preflight.put(pkg, current);
        }
        if (!preflight.has(BridgeClient.PACKAGES[0])) throw new IOException("Android Auto is not installed");
        state.put("sessionActive", true).put("enabled", true).put("hostApplied", false);
        state.put("preparation", new JSONObject().put("phase", "preparing").put("dpi", dpi).put("processToken", processToken).put("automatic", automatic));
        state.put("status", "Preparing " + dpi + " DPI. Wait for Ready before connecting Android Auto.");
        event("preparation-started", new JSONObject().put("dpi", dpi)); store.save(state);
        for (String pkg : BridgeClient.PACKAGES) {
            if (!preflight.has(pkg)) continue;
            boolean changed = configure(pkg, preflight.getJSONObject(pkg), dpi, 1, "prepare");
            if (!changed) verifyPersisted(pkg, dpi, 1);
        }
        long now = SystemClock.elapsedRealtime();
        HostDensity.Result confirmation = null;
        String confirmationFailure = null;
        try { confirmation = HostDensity.parse(bridge.displayDump()); }
        catch (Exception failure) { confirmationFailure = String.valueOf(failure); }
        // The app may have connected during the slow writes. Never advertise Ready
        // or clear the reconnect flag based only on the earlier disconnected snapshot.
        if (confirmation != null && (confirmation.anyAaOwned || confirmation.connected)) {
            state.remove("preparation");
            state.put("reconnectNeeded", true);
            state.put("status", "Android Auto connected before Ready. Wait for scaling to finish, then quickly disconnect and reconnect within 10 seconds.");
            event("preparation-connected-before-ready", new JSONObject().put("dpi", dpi));
            store.save(state); firstTick = true; return;
        }
        boolean confirmedClear = confirmation != null && confirmation.error == null;
        state.put("preparation", new JSONObject().put("phase", confirmedClear ? "ready" : "verify-disconnected").put("dpi", dpi).put("preparedAtElapsed", now)
                .put("expiresAtElapsed", now + 10 * 60 * 1000L).put("bootCount", bootCount()).put("processToken", processToken).put("automatic", automatic));
        state.put("reconnectNeeded", !confirmedClear);
        absentSince = -1;
        if (confirmedClear) {
            event("preparation-ready", new JSONObject().put("dpi", dpi));
            state.put("status", "Ready for the learned " + dpi + " DPI car. Connect Android Auto within 10 minutes. A different car DPI may still need a quick reconnect.");
        } else {
            event("preparation-awaiting-disconnected-check", new JSONObject().put("dpi", dpi));
            state.put("status", "Preparation is not Ready: disconnected display state could not be confirmed. Keep Android Auto disconnected and refresh status. "
                    + (confirmationFailure != null ? confirmationFailure : confirmation != null ? confirmation.error : "Display check unavailable"));
        }
        store.save(state);
        firstTick = true;
    }

    void enable() throws Exception {
        requireDump();
        if (state.has("pending")) { validate(); recoverPending(); }
        if (state.optBoolean("sessionActive")) {
            validate();
        } else {
            HostDensity.Result host = HostDensity.parse(bridge.displayDump());
            if (host.anyAaOwned || host.connected || host.error != null) {
                throw new IOException("Disconnect Android Auto before enabling for the first time. Phone preferences must be backed up while disconnected.");
            }
            captureBackup();
        }
        state.put("enabled", true);
        state.put("status", "Automatic scaling is enabled. Waiting for Android Auto.");
        event("enabled", null);
        store.save(state);
        firstTick = true;
    }

    void stopAndRestore() throws Exception {
        state.put("enabled", false);
        state.remove("preparation");
        state.put("status", "Stopping and restoring owned phone preferences…");
        store.save(state);
        if (state.optBoolean("sessionActive")) { requireDump(); validate(); recoverPending(); restore(); }
        else { state.put("status", "Automatic scaling is off."); store.save(state); }
    }

    void tick() throws Exception {
        if (!needsWork()) return;
        requireDump(); validate(); recoverPending();
        HostDensity.Result host = HostDensity.parse(bridge.displayDump());
        connected = host.connected || host.anyAaOwned;
        if (!state.optBoolean("enabled")) { restore(); return; }
        JSONObject preparation = state.optJSONObject("preparation");
        if (preparation != null && preparation.optBoolean("automatic") && !automaticCarActive
                && !host.anyAaOwned && !host.connected && host.error == null) {
            state.remove("preparation"); preparation = null;
            absentSince = SystemClock.elapsedRealtime();
            event("automatic-car-disconnected", null); store.save(state);
        }
        if (preparation != null) {
            if (host.error != null && !host.anyAaOwned && !host.connected) {
                setStatus("Waiting for reliable display information. Prepared settings are preserved; " + host.error);
                return;
            }
            if (preparation.optBoolean("automatic") && automaticCarActive) {
                // Keep the selected car ready for the complete Bluetooth session.
                // The original boot/clock guards still apply to the hold.
                preparation.put("expiresAtElapsed", SystemClock.elapsedRealtime() + 10 * 60 * 1000L);
            }
            boolean verifyingDisconnected = "verify-disconnected".equals(preparation.optString("phase"));
            PreparationWindow.Decision decision = PreparationWindow.evaluate("ready".equals(preparation.optString("phase")) || verifyingDisconnected,
                    host.anyAaOwned || host.connected, preparation.optInt("bootCount", -1), bootCount(),
                    preparation.optLong("preparedAtElapsed", -1), preparation.optLong("expiresAtElapsed", -1), SystemClock.elapsedRealtime(),
                    preparation.optString("processToken", null), processToken);
            if (decision == PreparationWindow.Decision.JOIN_HOST) {
                state.remove("preparation"); event("preparation-host-arrived", new JSONObject().put("dpi", preparation.optInt("dpi"))); store.save(state);
            } else if (decision == PreparationWindow.Decision.HOLD) {
                if (verifyingDisconnected) {
                    preparation.put("phase", "ready");
                    state.put("reconnectNeeded", false);
                    event("preparation-ready-after-fresh-check", new JSONObject().put("dpi", preparation.getInt("dpi")));
                    store.save(state);
                }
                absentSince = -1;
                long minutes = Math.max(1, (preparation.getLong("expiresAtElapsed") - SystemClock.elapsedRealtime() + 59999) / 60000);
                setStatus(preparation.optBoolean("automatic") && automaticCarActive
                        ? "Selected car connected. Scaling is ready at " + preparation.getInt("dpi") + " DPI while its Bluetooth connection remains active."
                        : "Ready for the learned " + preparation.getInt("dpi") + " DPI car. Connect within " + minutes + " minute(s). A different car DPI may need a quick reconnect.");
                return;
            } else {
                state.remove("preparation"); event("preparation-ended", null); store.save(state); restore();
                setStatus("Preparation ended without a car connection. Owned phone settings restored. Prepare again before your next drive." + restoreWarnings());
                return;
            }
        }
        if (host.error != null) {
            absentSince = -1;
            setStatus("Waiting: " + host.error + ". Existing owned preferences are preserved.");
            return;
        }
        if (host.safeToApply()) {
            absentSince = -1;
            if (firstTick || !state.optBoolean("hostApplied") || state.optInt("lastHostDpi") != host.dpi) {
                state.put("lastHostDpi", host.dpi);
                state.put("hostApplied", false);
                state.put("hostSurfaces", surfaces(host));
                store.save(state); // Host target is durable before any write.
                boolean changed = false;
                JSONObject packages = state.getJSONObject("backup").getJSONObject("packages");
                JSONObject preflight = new JSONObject();
                for (String pkg : BridgeClient.PACKAGES) {
                    if (!packages.has(pkg)) continue;
                    try { context.getPackageManager().getPackageInfo(pkg, 0); }
                    catch (PackageManager.NameNotFoundException absent) { continue; }
                    JSONObject current = bridge.get(pkg); validatePolicy(current);
                    assertOwnershipForApply(pkg, current);
                    preflight.put(pkg, current);
                }
                // Check every installed target before the first package mutation.
                // change() separately rechecks the complete effective policy immediately before each field.
                for (String pkg : BridgeClient.PACKAGES) {
                    if (!preflight.has(pkg)) continue;
                    JSONObject current = preflight.getJSONObject(pkg);
                    boolean packageChanged = configure(pkg, current, host.dpi, 1, "apply");
                    changed |= packageChanged;
                    // Every actual change already reloads and verifies full effective state
                    // before committing ownership. A no-op still needs persistence validation.
                    if (!packageChanged) verifyPersisted(pkg, host.dpi, 1);
                }
                state.put("hostApplied", true);
                state.put("reconnectNeeded", state.optBoolean("reconnectNeeded") || changed);
                event("host-applied", new JSONObject().put("dpi", host.dpi).put("changed", changed));
                store.save(state);
            }
            firstTick = false;
            setStatus("Android Auto connected: " + host.dpi + " DPI. "
                    + (state.optBoolean("reconnectNeeded") ? "Scaling updated. Reconnect Android Auto once if the bar or tiles keep their old size." : "Saved scaling already matches this host."));
        } else if (!host.anyAaOwned && !host.connected) {
            if (automaticCarActive && state.optInt("lastHostDpi", 0) >= 72 && state.optInt("lastHostDpi", 0) <= 640) {
                prepareAutomaticallyIfIdle();
                return;
            }
            if (state.getJSONObject("owned").length() == 0) {
                absentSince = -1;
                if (updateIdleState(state, "Automatic scaling is enabled. Waiting for Android Auto." + restoreWarnings())) store.save(state);
                return;
            }
            long now = SystemClock.elapsedRealtime();
            if (absentSince < 0) absentSince = now;
            if (now - absentSince >= 10000) {
                if (state.getJSONObject("owned").length() > 0) restore();
                state.put("hostApplied", false); state.put("reconnectNeeded", false); store.save(state);
                setStatus("Automatic scaling is enabled. Phone preferences restored; waiting for Android Auto." + restoreWarnings());
            } else setStatus("Android Auto disconnected. Waiting 10 seconds for display reconfiguration before restoring phone preferences.");
        }
    }

    void failure(Throwable failure) {
        try { state.put("status", "Needs attention: " + failure.getClass().getSimpleName() + ": " + failure.getMessage()); event("error", new JSONObject().put("message", String.valueOf(failure))); store.save(state); }
        catch (Exception ignored) {}
    }

    private void captureBackup() throws Exception {
        JSONObject inspection = bridge.inspect();
        String rawBefore = bridge.policyDump();
        JSONObject rawRows = parseRows(rawBefore);
        JSONObject packages = new JSONObject();
        for (String pkg : BridgeClient.PACKAGES) {
            try { context.getPackageManager().getPackageInfo(pkg, 0); }
            catch (PackageManager.NameNotFoundException absent) { continue; }
            JSONObject fields = bridge.get(pkg); validatePolicy(fields);
            packages.put(pkg, new JSONObject().put("fields", fields).put("rowPresent", rawRows.has(pkg)).put("rawRow", rawRows.opt(pkg)));
        }
        if (!packages.has(BridgeClient.PACKAGES[0])) throw new IOException("Android Auto is not installed or visible to the companion");
        String rawAfter = bridge.policyDump();
        if (!same(parseRows(rawBefore), parseRows(rawAfter))) throw new IOException("Vendor policy rows changed during backup; retry while disconnected");
        HostDensity.Result after = HostDensity.parse(bridge.displayDump());
        if (after.anyAaOwned || after.connected || after.error != null) throw new IOException("Android Auto appeared during backup; disconnect and retry");
        JSONObject backup = new JSONObject().put("fingerprint", Build.FINGERPRINT).put("capturedAtMillis", System.currentTimeMillis())
                .put("physicalDpi", bridge.physicalDpi()).put("runtimeBridgeSchema", inspection).put("schemaKey", schemaKey(inspection))
                .put("packages", packages).put("rawPolicyDump", rawBefore).put("rawRows", rawRows);
        state.put("backup", backup).put("sessionActive", true).put("owned", new JSONObject()).put("mutatedPackages", new JSONObject()).put("hostApplied", false).put("reconnectNeeded", false);
        state.remove("pending");
        state.remove("preparation");
        event("backup-captured", new JSONObject().put("packages", packages.names()));
        store.save(state); // Complete baseline becomes durable before enabling.
        validated = true;
    }

    private void validate() throws Exception {
        if (validated) return;
        if (state.optInt("formatVersion") != 1) throw new IOException("Unknown saved-state format");
        JSONObject backup = state.getJSONObject("backup");
        if (!Build.FINGERPRINT.equals(backup.getString("fingerprint"))) throw new IOException("Firmware changed since backup. Automatic writes are paused; saved backup is retained.");
        if (!backup.getString("schemaKey").equals(schemaKey(bridge.inspect()))) throw new IOException("Vendor policy interface changed since backup; refusing writes");
        validated = true;
    }

    private void recoverPending() throws Exception {
        if (!state.has("pending")) return;
        JSONObject pending = state.getJSONObject("pending");
        String pkg = pending.getString("package"), field = pending.getString("field");
        JSONObject before = pending.getJSONObject("before"), desired = copy(before).put(field, pending.getInt("value"));
        // A cached value is not proof that the vendor SQLite write succeeded.
        // dumpsys reloads this firmware's rows; classify only the reloaded result.
        JSONObject persistedRows = parseRows(bridge.policyDump());
        JSONObject actual = bridge.get(pkg);
        if (same(actual, desired)) {
            JSONObject persisted = persistedRows.optJSONObject(pkg);
            if (persisted == null || persisted.getInt(field) != pending.getInt("value")) throw new IOException("Interrupted write is not present in the vendor database; journal retained");
            own(pkg, field, pending.getInt("value"));
            event("recovered-completed-write", pending);
        } else if (same(actual, before)) event("recovered-unstarted-write", pending);
        else throw new IOException("Interrupted write has a conflicting readback for " + pkg + ". No preferences were overwritten; inspect the saved transaction journal.");
        state.remove("pending"); store.save(state);
    }

    private void assertOwnershipForApply(String pkg, JSONObject current) throws Exception {
        JSONObject own = state.getJSONObject("owned").optJSONObject(pkg);
        JSONObject baseline = state.getJSONObject("backup").getJSONObject("packages").getJSONObject(pkg).getJSONObject("fields");
        for (String field : new String[]{"appDpi", "isDpiSetting"}) {
            Object expected = own != null && own.has(field) ? own.get(field) : baseline.get(field);
            if (!same(current.get(field), expected)) throw new IOException("A user or another app changed " + pkg + " " + field + ". Automatic scaling is paused to preserve that edit.");
        }
    }

    private boolean configure(String pkg, JSONObject current, int dpi, int flag, String operation) throws Exception {
        boolean changed = false;
        if (current.getInt("isDpiSetting") != flag) {
            if (current.getInt("appDpi") == state.getJSONObject("backup").getInt("physicalDpi")) {
                int temporary = current.getInt("appDpi") == 160 ? 161 : 160;
                current = change(pkg, "appDpi", temporary, current, operation + "-stage-flag"); changed = true;
            }
            current = change(pkg, "isDpiSetting", flag, current, operation); changed = true;
        }
        if (current.getInt("appDpi") != dpi) { change(pkg, "appDpi", dpi, current, operation); changed = true; }
        return changed;
    }

    private JSONObject change(String pkg, String field, int value, JSONObject expected, String operation) throws Exception {
        if (expected.getInt(field) == value) return expected;
        JSONObject immediate = bridge.get(pkg);
        if (!same(immediate, expected)) throw new IOException("Policy changed concurrently before write: " + pkg);
        JSONObject pending = new JSONObject().put("package", pkg).put("field", field).put("value", value).put("before", copy(expected)).put("operation", operation).put("atMillis", System.currentTimeMillis());
        state.put("pending", pending);
        JSONObject mutated = state.optJSONObject("mutatedPackages"); if (mutated == null) { mutated = new JSONObject(); state.put("mutatedPackages", mutated); }
        mutated.put(pkg, true);
        store.save(state);
        JSONObject result = bridge.write(pkg, field, value);
        if (!Boolean.TRUE.equals(result.opt("setterResult"))) {
            throw new IOException("Vendor rejected a changed write for " + pkg + " " + field + "; pending journal retained for database-reload recovery");
        }
        JSONObject desired = copy(expected).put(field, value);
        JSONObject resultBefore = result.optJSONObject("beforePolicy"), resultAfter = result.optJSONObject("afterPolicy");
        if (resultBefore == null || resultAfter == null || !same(resultBefore.optJSONObject("fields"), expected)
                || !same(resultAfter.optJSONObject("fields"), desired) || !same(bridge.get(pkg), desired)) {
            throw new IOException("Write verification/collateral-field check failed for " + pkg + " " + field + "; transaction journal retained");
        }
        JSONObject persisted = parseRows(bridge.policyDump()).optJSONObject(pkg);
        if (persisted == null || persisted.getInt(field) != value || !same(bridge.get(pkg), desired)) {
            throw new IOException("Write did not survive vendor database reload for " + pkg + " " + field + "; transaction journal retained");
        }
        own(pkg, field, value);
        state.remove("pending");
        event("write-verified", new JSONObject().put("package", pkg).put("field", field).put("value", value).put("operation", operation).put("setterResult", result.opt("setterResult")));
        store.save(state);
        return desired;
    }

    private void own(String pkg, String field, int value) throws Exception {
        JSONObject owned = state.getJSONObject("owned");
        JSONObject fields = owned.optJSONObject(pkg); if (fields == null) { fields = new JSONObject(); owned.put(pkg, fields); }
        fields.put(field, value);
    }

    private void verifyPersisted(String pkg, int dpi, int flag) throws Exception {
        JSONObject beforeReload = bridge.get(pkg);
        JSONObject rows = parseRows(bridge.policyDump());
        JSONObject row = rows.optJSONObject(pkg);
        JSONObject mutated = state.optJSONObject("mutatedPackages");
        boolean untouchedAbsent = row == null
                && !state.getJSONObject("backup").getJSONObject("packages").getJSONObject(pkg).getBoolean("rowPresent")
                && mutated != null && !mutated.optBoolean(pkg)
                && (state.getJSONObject("owned").optJSONObject(pkg) == null || state.getJSONObject("owned").getJSONObject(pkg).length() == 0);
        if (!untouchedAbsent && (row == null || row.getInt("appDpi") != dpi || row.getInt("isDpiSetting") != flag)) throw new IOException("Persisted vendor row did not retain the requested DPI/flag for " + pkg);
        JSONObject afterReload = bridge.get(pkg);
        if (!same(beforeReload, afterReload) || afterReload.getInt("appDpi") != dpi || afterReload.getInt("isDpiSetting") != flag) throw new IOException("Policy reload did not retain effective settings for " + pkg);
    }

    private void restore() throws Exception {
        if (!state.optBoolean("sessionActive")) return;
        JSONObject owned = state.getJSONObject("owned"), saved = state.getJSONObject("backup").getJSONObject("packages");
        JSONArray conflicts = new JSONArray(), rowChanges = new JSONArray();
        for (String pkg : BridgeClient.PACKAGES) {
            JSONObject fields = owned.optJSONObject(pkg); if (fields == null) continue;
            JSONObject original = saved.getJSONObject(pkg).getJSONObject("fields");
            JSONObject current = bridge.get(pkg); validatePolicy(current);
            boolean dpiOwned = fields.has("appDpi") && current.getInt("appDpi") == fields.getInt("appDpi");
            boolean flagOwned = fields.has("isDpiSetting") && current.getInt("isDpiSetting") == fields.getInt("isDpiSetting");
            for (String field : new String[]{"appDpi", "isDpiSetting"}) {
                if (fields.has(field) && current.getInt(field) != fields.getInt(field)) { conflicts.put(pkg + " " + field + ": external edit preserved"); fields.remove(field); }
            }
            if (dpiOwned && flagOwned) {
                boolean changed = configure(pkg, current, original.getInt("appDpi"), original.getInt("isDpiSetting"), "restore");
                if (!changed) verifyPersisted(pkg, original.getInt("appDpi"), original.getInt("isDpiSetting"));
                fields.remove("appDpi"); fields.remove("isDpiSetting");
            } else {
                boolean restoredAny = false;
                if (flagOwned && current.getInt("isDpiSetting") != original.getInt("isDpiSetting")) {
                    if (current.getInt("appDpi") == state.getJSONObject("backup").getInt("physicalDpi") && !dpiOwned) {
                        conflicts.put(pkg + " isDpiSetting: preserved because restoring it would require changing an externally edited DPI");
                    } else {
                        current = change(pkg, "isDpiSetting", original.getInt("isDpiSetting"), current, "restore-owned-flag");
                        restoredAny = true;
                    }
                }
                if (dpiOwned && current.getInt("appDpi") != original.getInt("appDpi")) { current = change(pkg, "appDpi", original.getInt("appDpi"), current, "restore-owned-dpi"); restoredAny = true; }
                if (restoredAny) verifyPersisted(pkg, current.getInt("appDpi"), current.getInt("isDpiSetting"));
                fields.remove("isDpiSetting");
                fields.remove("appDpi");
            }
            owned.remove(pkg); store.save(state);
            if (!saved.getJSONObject(pkg).getBoolean("rowPresent")) rowChanges.put(pkg + ": original row was absent; restored values remain in a materialized row (vendor exposes no delete API)");
        }
        state.put("restoreConflicts", conflicts).put("rowPresenceChanges", rowChanges).put("hostApplied", false).put("reconnectNeeded", false);
        if (!state.optBoolean("enabled")) state.put("sessionActive", false);
        event("restore-completed", new JSONObject().put("preservedExternalEdits", conflicts).put("rowPresenceChanges", rowChanges));
        state.put("status", (state.optBoolean("enabled") ? "Phone preferences restored. Automatic scaling is waiting for Android Auto." : "Automatic scaling is off. Owned phone preferences restored.")
                + (conflicts.length() > 0 ? " External edits preserved: " + conflicts : "") + (rowChanges.length() > 0 ? " " + rowChanges : ""));
        store.save(state);
    }

    private void requireDump() throws IOException {
        if (context.checkSelfPermission(Manifest.permission.DUMP) != PackageManager.PERMISSION_GRANTED) throw new IOException("One-time DUMP permission setup is required before enabling. Read the setup guide.");
    }
    private int bootCount() {
        try { return android.provider.Settings.Global.getInt(context.getContentResolver(), android.provider.Settings.Global.BOOT_COUNT, -1); }
        catch (RuntimeException unavailable) { return -1; }
    }
    private static void validatePolicy(JSONObject fields) throws Exception {
        if (fields.getDouble("appDpiScale") != 1.0 || fields.getInt("immutable") != 0) throw new IOException("Policy requires appDpiScale=1 and immutable=0; refusing automatic scaling");
        for (String f : new String[]{"appDpi", "isDpiSetting"}) if (!(fields.get(f) instanceof Number)) throw new IOException("Unsupported policy field type");
    }
    private static String schemaKey(JSONObject inspection) throws Exception {
        return inspection.getJSONObject("interface").getJSONArray("declaredMethods").toString() + "\n" + inspection.getJSONArray("allowlistedPackageGetters").toString();
    }
    private static JSONObject copy(JSONObject object) throws Exception { return new JSONObject(object.toString()); }
    static boolean same(Object a, Object b) throws Exception {
        if (a == b) return true;
        if (a == null || b == null || a == JSONObject.NULL || b == JSONObject.NULL) return false;
        if (a instanceof Number && b instanceof Number) return Double.compare(((Number)a).doubleValue(), ((Number)b).doubleValue()) == 0;
        if (a instanceof JSONObject && b instanceof JSONObject) {
            JSONObject x = (JSONObject)a, y = (JSONObject)b;
            if (x.length() != y.length()) return false;
            Iterator<String> keys = x.keys(); while (keys.hasNext()) { String k = keys.next(); if (!y.has(k) || !same(x.get(k), y.get(k))) return false; }
            return true;
        }
        if (a instanceof JSONArray && b instanceof JSONArray) {
            JSONArray x = (JSONArray)a, y = (JSONArray)b; if (x.length() != y.length()) return false;
            for (int i = 0; i < x.length(); i++) if (!same(x.get(i), y.get(i))) return false; return true;
        }
        return a.equals(b);
    }
    private static JSONObject parseRows(String dump) throws Exception {
        long started = SystemClock.elapsedRealtime();
        int rowCount = 0;
        boolean ok = false;
        try {
        int start = dump.indexOf("Policy list:");
        if (start < 0 || dump.contains("Permission Denial")) throw new IOException("Vendor policy dump has no readable rows");
        JSONObject rows = new JSONObject();
        Matcher matcher = POLICY_ROW_PATTERN.matcher(dump.substring(start));
        Matcher integerValue = INTEGER_VALUE_PATTERN.matcher("");
        Matcher decimalValue = DECIMAL_VALUE_PATTERN.matcher("");
        while (matcher.find()) {
            JSONObject row = new JSONObject();
            for (String part : matcher.group(1).split(",")) {
                int equal = part.indexOf('='); if (equal < 0) throw new IOException("Unknown policy row format");
                String key = part.substring(0, equal).trim(), value = part.substring(equal + 1).trim();
                if (row.has(key)) throw new IOException("Duplicate policy row field");
                if (value.startsWith("'") && value.endsWith("'")) row.put(key, value.substring(1, value.length() - 1));
                else if (integerValue.reset(value).matches()) row.put(key, Long.parseLong(value));
                else if (decimalValue.reset(value).matches()) row.put(key, Double.parseDouble(value));
                else throw new IOException("Unknown policy row value");
            }
            String pkg = row.getString("packageName"); if (rows.has(pkg)) throw new IOException("Duplicate policy row package"); rows.put(pkg, row); rowCount++;
        }
        if (rows.length() == 0) throw new IOException("Policy list is empty; cannot establish row presence");
        ok = true;
        return rows;
        } finally {
            android.util.Log.i("HBAutoPerf", "parse-rows durationMs=" + (SystemClock.elapsedRealtime() - started) + " rows=" + rowCount + " ok=" + ok);
        }
    }
    private static JSONArray surfaces(HostDensity.Result host) throws Exception {
        JSONArray result = new JSONArray();
        for (HostDensity.Surface s : host.surfaces) result.put(new JSONObject().put("name", s.name).put("dpi", s.dpi).put("kind", s.kind));
        return result;
    }
    private void event(String name, JSONObject details) throws Exception {
        JSONArray old = state.optJSONArray("events"), events = new JSONArray();
        if (old != null) for (int i = Math.max(0, old.length() - 99); i < old.length(); i++) events.put(old.get(i));
        events.put(new JSONObject().put("atMillis", System.currentTimeMillis()).put("event", name).put("details", details == null ? JSONObject.NULL : details));
        state.put("events", events);
    }
    private void setStatus(String text) throws Exception { if (!text.equals(state.optString("status"))) { state.put("status", text); store.save(state); } }
    static boolean updateIdleState(JSONObject state, String text) throws Exception {
        if (!state.optBoolean("hostApplied") && !state.optBoolean("reconnectNeeded") && text.equals(state.optString("status"))) return false;
        state.put("hostApplied", false).put("reconnectNeeded", false).put("status", text);
        return true;
    }
    private String restoreWarnings() {
        JSONArray conflicts = state.optJSONArray("restoreConflicts"), rows = state.optJSONArray("rowPresenceChanges");
        return (conflicts != null && conflicts.length() > 0 ? " External edits preserved: " + conflicts : "")
                + (rows != null && rows.length() > 0 ? " " + rows : "");
    }
}
