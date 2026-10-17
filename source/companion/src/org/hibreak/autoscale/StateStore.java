package org.hibreak.autoscale;

import android.content.Context;
import android.util.AtomicFile;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;

/** Whole journal + immutable session backup are committed before each mutation. */
final class StateStore {
    private static final Object LOCK = new Object();
    private final AtomicFile file;
    StateStore(Context context) { file = new AtomicFile(new File(context.getFilesDir(), "automatic-state.json")); }
    JSONObject load() throws Exception {
        synchronized (LOCK) {
            try { return new JSONObject(new String(file.readFully(), StandardCharsets.UTF_8)); }
            catch (FileNotFoundException absent) { return new JSONObject().put("formatVersion", 1).put("enabled", false).put("sessionActive", false).put("owned", new JSONObject()).put("events", new JSONArray()).put("status", "Automatic scaling is off."); }
        }
    }
    void save(JSONObject state) throws Exception {
        long started = android.os.SystemClock.elapsedRealtime();
        synchronized (LOCK) {
            long entered = android.os.SystemClock.elapsedRealtime();
            long opened = entered, encoded = entered, written = entered;
            int byteCount = 0;
            boolean ok = false;
            FileOutputStream output = null;
            try {
                output = file.startWrite();
                opened = android.os.SystemClock.elapsedRealtime();
                byte[] bytes = state.toString(2).getBytes(StandardCharsets.UTF_8);
                byteCount = bytes.length;
                encoded = android.os.SystemClock.elapsedRealtime();
                output.write(bytes);
                written = android.os.SystemClock.elapsedRealtime();
                file.finishWrite(output);
                ok = true;
            } catch (Exception failure) { if (output != null) file.failWrite(output); throw failure; }
            finally {
                long finished = android.os.SystemClock.elapsedRealtime();
                android.util.Log.i("HBAutoPerf", "state-save durationMs=" + (finished - started) + " lockWaitMs=" + (entered - started)
                        + " openMs=" + (opened - entered) + " serializeMs=" + (encoded - opened) + " writeMs=" + (written - encoded)
                        + " commitMs=" + (finished - written) + " bytes=" + byteCount + " ok=" + ok);
            }
        }
    }
    static boolean workNeeded(JSONObject state) {
        return state.optBoolean("enabled") || state.has("pending") || (state.optJSONObject("owned") != null && state.optJSONObject("owned").length() > 0);
    }
}
