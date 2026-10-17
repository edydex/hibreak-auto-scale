package org.hibreak.autoscale;

import android.content.Context;
import org.json.*;
import java.io.IOException;
import java.util.*;

/** Independent synthetic cache/database model, not a vendor-service implementation. */
final class BridgeClient {
    static final String[] PACKAGES = {"com.google.android.projection.gearhead", "com.google.android.apps.maps", "com.google.android.googlequicksearchbox"};
    enum Write { NORMAL, FALSE_PERSISTED, FALSE_UNSTARTED, CACHE_ONLY, THROW_AFTER_PERSIST, COLLATERAL }
    static final Map<String,JSONObject> live = new LinkedHashMap<String,JSONObject>();
    static final Map<String,JSONObject> database = new LinkedHashMap<String,JSONObject>();
    static final Map<String,JSONObject> defaults = new LinkedHashMap<String,JSONObject>();
    static final List<String> calls = new ArrayList<String>();
    static Write nextWrite;
    static boolean connected, retainCacheOnReload;
    static String schema = "synthetic-v1", dumpOverride;
    static int writes;
    BridgeClient(Context context) {}
    static JSONObject policy(int dpi, int enabled) { return new JSONObject().put("appDpi", dpi).put("isDpiSetting", enabled).put("appDpiScale", 1.0).put("immutable", 0).put("appTextEnhance", 2).put("contrast", 17); }
    static void reset() {
        live.clear(); database.clear(); defaults.clear(); calls.clear(); writes = 0; nextWrite = Write.NORMAL;
        connected = false; retainCacheOnReload = false; schema = "synthetic-v1"; dumpOverride = null;
        for (String pkg : PACKAGES) { defaults.put(pkg, policy(276, 0)); database.put(pkg, policy(276, 0)); live.put(pkg, policy(276, 0)); }
        // An unrelated row keeps a genuine readable policy list when a target row is absent.
        database.put("example.unrelated", policy(300, 0));
    }
    static void externalEdit(String pkg, String field, int value) { database.get(pkg).put(field, value); live.get(pkg).put(field, value); }
    JSONObject inspect() { return new JSONObject().put("interface", new JSONObject().put("declaredMethods", new JSONArray().put(schema))).put("allowlistedPackageGetters", new JSONArray().put("getPolicyByPackage")); }
    JSONObject get(String pkg) { calls.add("get:" + pkg); return StateStore.copy(live.get(pkg)); }
    int physicalDpi() { return 276; }
    void close() {}
    String displayDump() {
        return "Display Devices:\n" + (connected ? "DisplayDeviceInfo{\"GhFacetBar\": 800 x 480, density 160, type VIRTUAL, state ON, owner " + PACKAGES[0] + " (uid 99)}\n" : "DisplayDeviceInfo{\"Built-in Screen\": 720 x 1440, density 276, type INTERNAL, state ON}\n");
    }
    String policyDump() {
        calls.add("reload");
        if (!retainCacheOnReload) for (String pkg : PACKAGES) live.put(pkg, StateStore.copy(database.containsKey(pkg) ? database.get(pkg) : defaults.get(pkg)));
        if (dumpOverride != null) return dumpOverride;
        StringBuilder out = new StringBuilder("Policy list:\n");
        for (Map.Entry<String,JSONObject> entry : database.entrySet()) {
            out.append("DisplayPolicy{packageName='").append(entry.getKey()).append("'");
            Iterator<String> keys = entry.getValue().keys();
            while (keys.hasNext()) { String key = keys.next(); out.append(", ").append(key).append('=').append(entry.getValue().get(key)); }
            out.append("}\n");
        }
        return out.toString();
    }
    JSONObject write(String pkg, String field, int value) throws Exception {
        writes++; calls.add("write:" + pkg + ":" + field);
        if (StateStore.durable == null || !StateStore.durable.has("pending")) throw new AssertionError("Vendor write occurred before durable journal intent");
        JSONObject pending = StateStore.durable.getJSONObject("pending");
        if (!pkg.equals(pending.getString("package")) || !field.equals(pending.getString("field")) || pending.getInt("value") != value) throw new AssertionError("Wrong durable journal intent");
        JSONObject before = StateStore.copy(live.get(pkg)), after = StateStore.copy(before).put(field, value);
        Write mode = nextWrite; nextWrite = Write.NORMAL;
        if (mode != Write.FALSE_UNSTARTED) {
            if (mode == Write.COLLATERAL) after.put("contrast", 99);
            live.put(pkg, StateStore.copy(after));
            if (mode != Write.CACHE_ONLY) database.put(pkg, StateStore.copy(after));
        }
        if (mode == Write.THROW_AFTER_PERSIST) throw new IOException("Injected transport loss after persisted setter");
        return new JSONObject().put("setterResult", mode != Write.FALSE_PERSISTED && mode != Write.FALSE_UNSTARTED)
                .put("beforePolicy", new JSONObject().put("fields", before))
                .put("afterPolicy", new JSONObject().put("fields", StateStore.copy(live.get(pkg))));
    }
}
