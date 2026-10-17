package org.hibreak.autoscale;

import android.content.Context;
import android.os.Build;
import org.json.*;
import java.lang.reflect.*;

/** Fault-injects the unmodified production ScaleEngine transaction and restore paths. */
public final class RecoveryTest {
    static final String AA = BridgeClient.PACKAGES[0];
    static final String FINGERPRINT = "synthetic/HiBreak/test:14/host-test";
    static int checks, cases;
    interface Action { void run() throws Exception; }
    static void check(boolean okay, String detail) { checks++; if (!okay) throw new AssertionError(detail); }
    static void rejects(Action action, String contains) throws Exception {
        try { action.run(); throw new AssertionError("Expected refusal: " + contains); }
        catch (Exception error) { check(error.getMessage() != null && error.getMessage().contains(contains), "Refusal should explain " + contains + ", got " + error); }
    }
    static Object invoke(ScaleEngine engine, String name, Class<?>[] types, Object... args) throws Exception {
        Method method = ScaleEngine.class.getDeclaredMethod(name, types); method.setAccessible(true);
        try { return method.invoke(engine, args); }
        catch (InvocationTargetException error) { Throwable cause = error.getCause(); if (cause instanceof Exception) throw (Exception)cause; throw (Error)cause; }
    }
    static void change(ScaleEngine engine, String field, int value) throws Exception {
        JSONObject before = StateStore.copy(BridgeClient.live.get(AA));
        invoke(engine, "change", new Class<?>[]{String.class,String.class,int.class,JSONObject.class,String.class}, AA, field, value, before, "host-fault-test");
    }
    static ScaleEngine fresh() throws Exception {
        StateStore.reset(); BridgeClient.reset(); Build.FINGERPRINT = FINGERPRINT; Context.dumpGranted = true; android.os.SystemClock.now = 1000;
        ScaleEngine engine = new ScaleEngine(new Context()); engine.enable();
        check(StateStore.durable.has("backup") && StateStore.durable.getJSONObject("owned").length() == 0, "Production enable captures baseline before mutations");
        return engine;
    }
    static ScaleEngine restart() throws Exception { return new ScaleEngine(new Context()); }
    static boolean event(String name) {
        JSONArray entries = StateStore.durable.getJSONArray("events");
        for (int i = 0; i < entries.length(); i++) if (name.equals(((JSONObject)entries.get(i)).getString("event"))) return true;
        return false;
    }
    static void originalPolicies() throws Exception {
        for (String pkg : BridgeClient.PACKAGES) check(ScaleEngine.same(BridgeClient.live.get(pkg), BridgeClient.policy(276,0)), "Exact original effective policy restored: " + pkg);
    }
    static void caseDone(String name) { cases++; System.out.println("PASS " + name); }

    public static void main(String[] args) throws Exception {
        ScaleEngine engine = fresh(); BridgeClient.connected = true; engine.tick();
        for (String pkg : BridgeClient.PACKAGES) {
            check(BridgeClient.database.get(pkg).getInt("appDpi") == 160 && BridgeClient.database.get(pkg).getInt("isDpiSetting") == 1, "Host density/flag persisted");
            check(BridgeClient.live.get(pkg).getInt("contrast") == 17 && BridgeClient.live.get(pkg).getInt("appTextEnhance") == 2, "Unowned fields unchanged");
        }
        engine.stopAndRestore(); originalPolicies();
        check(!StateStore.durable.optBoolean("sessionActive") && StateStore.durable.getJSONObject("owned").length() == 0, "Stop completes recovery ownership");
        caseDone("normal production enable/tick/stop restores full effective policies");

        for (BridgeClient.Write failure : new BridgeClient.Write[]{BridgeClient.Write.FALSE_PERSISTED, BridgeClient.Write.FALSE_UNSTARTED, BridgeClient.Write.CACHE_ONLY, BridgeClient.Write.THROW_AFTER_PERSIST}) {
            engine = fresh(); BridgeClient.nextWrite = failure; final ScaleEngine selected = engine;
            rejects(() -> change(selected,"appDpi",160), failure == BridgeClient.Write.CACHE_ONLY ? "database reload" : failure == BridgeClient.Write.THROW_AFTER_PERSIST ? "transport loss" : "pending journal retained");
            check(StateStore.durable.has("pending"), "Failed write retains durable pending intent");
            check(StateStore.durable.getJSONObject("owned").length() == 0, "Unverified write not committed as ownership");
            int beforeRestart = BridgeClient.writes;
            restart().stopAndRestore(); originalPolicies();
            boolean persisted = failure == BridgeClient.Write.FALSE_PERSISTED || failure == BridgeClient.Write.THROW_AFTER_PERSIST;
            check(event(persisted ? "recovered-completed-write" : "recovered-unstarted-write"), "Restart classifies independent database-reloaded outcome");
            check(BridgeClient.writes == beforeRestart + (persisted ? 1 : 0), "Recovery replays no setter; only verified owned restoration may write");
            check(!StateStore.durable.has("pending"), "Recovered journal cleared");
            caseDone("restart after " + failure);
        }

        engine = fresh(); StateStore.failNext = true; final ScaleEngine beforeJournal = engine;
        rejects(() -> change(beforeJournal,"appDpi",160), "commit failure");
        check(BridgeClient.writes == 0 && !StateStore.durable.has("pending"), "Failed journal save prevents vendor write");
        restart().stopAndRestore(); originalPolicies(); caseDone("journal commit failure before mutation");

        engine = fresh(); StateStore.failNextWithoutPending = true; final ScaleEngine afterSetter = engine;
        rejects(() -> change(afterSetter,"appDpi",160), "commit failure");
        check(StateStore.durable.has("pending") && BridgeClient.database.get(AA).getInt("appDpi") == 160, "Failed final commit preserves previous durable journal after setter");
        restart().stopAndRestore(); originalPolicies();
        check(event("recovered-completed-write"), "Restart recovers commit-interrupted completed write");
        caseDone("state commit failure after persisted setter");

        engine = fresh(); BridgeClient.nextWrite = BridgeClient.Write.COLLATERAL; final ScaleEngine collateral = engine;
        rejects(() -> change(collateral,"appDpi",160), "collateral-field");
        int writes = BridgeClient.writes;
        rejects(() -> restart().stopAndRestore(), "conflicting readback");
        check(BridgeClient.writes == writes && StateStore.durable.has("pending"), "Conflicting transaction neither overwritten nor discarded");
        check(BridgeClient.live.get(AA).getInt("contrast") == 99, "Collateral/external field preserved for inspection");
        caseDone("conflicting full-policy recovery refuses further writes");

        engine = fresh(); BridgeClient.connected = true; engine.tick();
        BridgeClient.externalEdit(AA,"appDpi",200); engine.stopAndRestore();
        check(BridgeClient.live.get(AA).getInt("appDpi") == 200, "Externally edited DPI preserved");
        check(BridgeClient.live.get(AA).getInt("isDpiSetting") == 0, "Still-owned flag restored independently");
        check(StateStore.durable.getJSONArray("restoreConflicts").length() == 1, "External edit reported");
        check(StateStore.durable.getJSONObject("owned").length() == 0, "Released ownership cannot overwrite external edit later");
        caseDone("external edit during active ownership is preserved on stop");

        engine = fresh(); BridgeClient.connected = true; engine.tick();
        BridgeClient.externalEdit(AA,"appDpi",276); engine.stopAndRestore();
        check(BridgeClient.live.get(AA).getInt("appDpi") == 276 && BridgeClient.live.get(AA).getInt("isDpiSetting") == 1, "Externally owned physical DPI prevents staging another DPI solely to restore flag");
        check(StateStore.durable.getJSONArray("restoreConflicts").length() == 2, "Both the external DPI and safely retained flag are reported");
        check(StateStore.durable.getJSONObject("owned").length() == 0, "Unsafe flag staging is not retried after ownership release");
        caseDone("external physical DPI prevents destructive flag-restoration staging");

        engine = fresh(); BridgeClient.connected = true; engine.tick();
        BridgeClient.externalEdit(AA,"appTextEnhance",3); BridgeClient.externalEdit(AA,"contrast",22); engine.stopAndRestore();
        check(BridgeClient.live.get(AA).getInt("appDpi") == 276 && BridgeClient.live.get(AA).getInt("isDpiSetting") == 0, "Owned DPI/flag restored with other settings edited");
        check(BridgeClient.live.get(AA).getInt("appTextEnhance") == 3 && BridgeClient.live.get(AA).getInt("contrast") == 22, "Unowned user enhancement/contrast edits survive restoration");
        caseDone("unowned user fields survive owned-field restoration");

        engine = fresh(); BridgeClient.externalEdit(AA,"appDpi",200); BridgeClient.connected = true; final ScaleEngine external = engine;
        rejects(() -> external.tick(), "Automatic scaling is paused");
        check(BridgeClient.writes == 0, "All target preflights complete before first mutation");
        caseDone("external edit before apply blocks all package writes");

        engine = fresh(); Build.FINGERPRINT = "synthetic/changed/firmware";
        rejects(() -> restart().stopAndRestore(), "Firmware changed");
        check(BridgeClient.writes == 0 && StateStore.durable.has("backup"), "Firmware drift retains backup and refuses writes");
        caseDone("firmware drift refuses restoration mutation");

        engine = fresh(); BridgeClient.schema = "synthetic-v2";
        rejects(() -> restart().stopAndRestore(), "interface changed");
        check(BridgeClient.writes == 0 && StateStore.durable.has("backup"), "Schema drift retains backup and refuses writes");
        caseDone("vendor interface drift refuses restoration mutation");

        engine = fresh(); BridgeClient.nextWrite = BridgeClient.Write.FALSE_PERSISTED; final ScaleEngine missingRow = engine;
        rejects(() -> change(missingRow,"appDpi",160), "pending journal retained");
        BridgeClient.database.remove(AA); BridgeClient.retainCacheOnReload = true; writes = BridgeClient.writes;
        rejects(() -> restart().stopAndRestore(), "not present in the vendor database");
        check(StateStore.durable.has("pending") && BridgeClient.writes == writes, "Effective/cache value cannot replace missing persistent row proof");
        caseDone("missing persisted row cannot validate completed interrupted write");

        engine = fresh(); BridgeClient.database.remove(BridgeClient.PACKAGES[1]); BridgeClient.live.put(BridgeClient.PACKAGES[1], BridgeClient.policy(276,0));
        // Capture a fresh genuine absent-row baseline rather than editing the saved backup.
        engine.stopAndRestore(); engine.enable(); BridgeClient.connected = true; engine.tick(); engine.stopAndRestore(); originalPolicies();
        check(BridgeClient.database.containsKey(BridgeClient.PACKAGES[1]), "No delete API is invented for originally absent row");
        check(StateStore.durable.getJSONArray("rowPresenceChanges").length() == 1, "Materialized original-absent row explicitly reported");
        caseDone("originally absent target row restores values and reports materialization");

        engine = fresh(); engine.stopAndRestore();
        BridgeClient.defaults.put(AA, BridgeClient.policy(160,1)); BridgeClient.live.put(AA, BridgeClient.policy(160,1)); BridgeClient.database.remove(AA);
        engine.enable(); BridgeClient.connected = true; engine.tick();
        check(!BridgeClient.database.containsKey(AA), "No-op baseline already at host density does not invent target database row");
        check(StateStore.durable.getJSONObject("owned").optJSONObject(AA) == null, "No-op absent row gains no ownership");
        check(!StateStore.durable.getJSONObject("mutatedPackages").optBoolean(AA), "No-op absent row is not marked mutated");
        engine.stopAndRestore();
        check(StateStore.durable.getJSONArray("rowPresenceChanges").length() == 0, "No-op absent row needs no materialization warning");
        caseDone("untouched absent row already matching host remains absent");

        engine = fresh(); Context.dumpGranted = false; BridgeClient.connected = true; final ScaleEngine denied = engine;
        rejects(() -> denied.tick(), "DUMP permission"); check(BridgeClient.writes == 0, "Permission loss prevents writes");
        caseDone("DUMP permission loss blocks apply");
        System.out.println("PASS " + checks + " assertions in " + cases + " recovery fault cases; actual unmodified ScaleEngine with host-only dependencies, no phone/vendor or Android AtomicFile coverage.");
    }
}
