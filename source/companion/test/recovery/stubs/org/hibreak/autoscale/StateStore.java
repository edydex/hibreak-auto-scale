package org.hibreak.autoscale;

import android.content.Context;
import org.json.*;
import java.io.IOException;

/** Synthetic durable snapshots and injected commit failures, not Android AtomicFile. */
final class StateStore {
    static JSONObject durable;
    static int saves;
    static boolean failNext, failNextWithoutPending;
    StateStore(Context context) {}
    JSONObject load() {
        return durable == null ? new JSONObject().put("formatVersion", 1).put("enabled", false).put("sessionActive", false)
                .put("owned", new JSONObject()).put("events", new JSONArray()).put("status", "Automatic scaling is off.") : copy(durable);
    }
    void save(JSONObject state) throws IOException {
        if (failNext || (failNextWithoutPending && !state.has("pending"))) {
            failNext = false; failNextWithoutPending = false; throw new IOException("Injected host state commit failure");
        }
        durable = copy(state); saves++;
    }
    static JSONObject copy(JSONObject value) { return new JSONObject(value.toString()); }
    static void reset() { durable = null; saves = 0; failNext = false; failNextWithoutPending = false; }
    // This helper is the same read-only predicate used by production StateStore.
    static boolean workNeeded(JSONObject state) { return state.optBoolean("enabled") || state.has("pending") || (state.optJSONObject("owned") != null && state.optJSONObject("owned").length() > 0); }
}
