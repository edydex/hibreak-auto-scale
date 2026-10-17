package org.hibreak.autoscale;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.hardware.display.DisplayManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Process;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.Display;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Date;
import java.util.IdentityHashMap;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.TimeUnit;

/** Read-only access probe. This prototype invokes no settings setters or monitor. */
public final class ProbeActivity extends Activity {
    private static final String TAG = "HBAutoScale";
    private static final String SERVICE = "xrz_display_policy_service";
    private static final String[] PACKAGES = {
        "com.google.android.projection.gearhead", "com.google.android.apps.maps", "com.google.android.googlequicksearchbox"
    };
    private TextView status;
    private Button rerun;
    private boolean inProgress;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(28, 28, 28, 28);
        layout.setBackgroundColor(Color.WHITE);
        TextView title = new TextView(this);
        title.setText("HiBreak Auto Scale\nAccess diagnostics");
        title.setTextSize(25);
        title.setTextColor(Color.BLACK);
        layout.addView(title);
        TextView explanation = new TextView(this);
        explanation.setText("This prototype reads display information and the Android Auto, Maps, and Google display policies. It does not change scaling or start a background monitor.");
        explanation.setTextSize(17);
        explanation.setTextColor(Color.BLACK);
        explanation.setPadding(0, 18, 0, 18);
        layout.addView(explanation);
        rerun = new Button(this);
        rerun.setText("Run diagnostics again");
        rerun.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { runProbe(); }
        });
        layout.addView(rerun);
        ScrollView scroller = new ScrollView(this);
        status = new TextView(this);
        status.setTextColor(Color.BLACK);
        status.setTextSize(16);
        status.setTextIsSelectable(true);
        status.setPadding(0, 16, 0, 16);
        scroller.addView(status);
        layout.addView(scroller, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(layout);
        runProbe();
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (intent.getBooleanExtra("probe", false)) runProbe();
    }

    private void runProbe() {
        if (inProgress) return;
        inProgress = true;
        rerun.setEnabled(false);
        status.setText("Reading policies and displays…");
        new Thread(new Runnable() {
            @Override public void run() {
                JSONObject report = collectReport();
                File file = null;
                try {
                    File directory = getExternalFilesDir(null);
                    if (directory == null) directory = getFilesDir();
                    file = new File(directory, "probe.json");
                    put(report, "reportPath", file.getAbsolutePath());
                    byte[] bytes = report.toString(2).getBytes(StandardCharsets.UTF_8);
                    try (FileOutputStream output = new FileOutputStream(file)) { output.write(bytes); }
                } catch (Throwable error) {
                    put(report, "saveError", error(error));
                }
                String json = report.toString();
                int chunks = (json.length() + 2799) / 2800;
                for (int i = 0; i < chunks; i++) {
                    Log.i(TAG, "PROBE " + (i + 1) + "/" + chunks + " " + json.substring(i * 2800, Math.min(json.length(), (i + 1) * 2800)));
                }
                final String summary = summary(report);
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        status.setText(summary);
                        inProgress = false;
                        rerun.setEnabled(true);
                    }
                });
            }
        }, "HiBreak-read-only-probe").start();
    }

    private JSONObject collectReport() {
        JSONObject report = new JSONObject();
        put(report, "prototypeVersion", "0.2-process-probe");
        put(report, "readOnly", true);
        SimpleDateFormat date = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        date.setTimeZone(TimeZone.getTimeZone("UTC"));
        put(report, "generatedAtUtc", date.format(new Date()));
        put(report, "uid", Process.myUid());
        put(report, "package", getPackageName());
        put(report, "buildFingerprint", Build.FINGERPRINT);
        put(report, "manufacturer", Build.MANUFACTURER);
        put(report, "model", Build.MODEL);
        put(report, "sdkInt", Build.VERSION.SDK_INT);
        JSONObject vendor = new JSONObject();
        put(report, "vendorService", vendor);
        put(vendor, "name", SERVICE);
        try {
            Object manager = getSystemService(SERVICE);
            put(vendor, "available", manager != null);
            if (manager != null) {
                put(vendor, "class", manager.getClass().getName());
                put(vendor, "declaredMethods", methods(manager.getClass().getDeclaredMethods()));
                put(vendor, "publicMethods", methods(manager.getClass().getMethods()));
                Method getter = manager.getClass().getMethod("getPolicyByPackage", String.class);
                if (Modifier.isStatic(getter.getModifiers()) || getter.getReturnType() == Void.TYPE) {
                    throw new IllegalStateException("Unexpected package-policy getter signature");
                }
                put(vendor, "getterSignature", getter.toGenericString());
                JSONObject policies = new JSONObject();
                put(vendor, "policies", policies);
                int successfulPolicies = 0;
                for (String packageName : PACKAGES) {
                    try {
                        Object policy = getter.invoke(manager, packageName);
                        put(policies, packageName, serialize(policy, 0, new IdentityHashMap<Object, Boolean>()));
                        if (policy != null) successfulPolicies++;
                    } catch (Throwable failure) {
                        put(policies, packageName, new JSONObject().put("error", error(failure)));
                    }
                }
                put(vendor, "nonNullPolicyReadCount", successfulPolicies);
                put(vendor, "probeSucceeded", successfulPolicies == PACKAGES.length);
            }
        } catch (Throwable failure) {
            put(vendor, "error", error(failure));
            put(vendor, "probeSucceeded", false);
        }
        put(report, "appProcessProbe", appProcessProbe());
        try { put(report, "displays", displayReport()); }
        catch (Throwable failure) {
            put(report, "displays", new JSONArray());
            put(report, "displayEnumerationError", error(failure));
        }
        boolean dumpGranted = checkSelfPermission(Manifest.permission.DUMP) == PackageManager.PERMISSION_GRANTED;
        put(report, "dumpPermissionGranted", dumpGranted);
        if (dumpGranted) put(report, "dumpsysDisplay", dumpDisplays());
        else put(report, "dumpsysDisplay", new JSONObject());
        return report;
    }

    @SuppressWarnings("deprecation")
    private JSONArray displayReport() {
        JSONArray result = new JSONArray();
        DisplayManager manager = (DisplayManager) getSystemService(Context.DISPLAY_SERVICE);
        if (manager == null) return result;
        for (Display display : manager.getDisplays()) {
            JSONObject item = new JSONObject();
            try {
                put(item, "id", display.getDisplayId());
                put(item, "name", display.getName());
                put(item, "valid", display.isValid());
                put(item, "flags", display.getFlags());
                put(item, "state", display.getState());
                put(item, "rotation", display.getRotation());
                DisplayMetrics metrics = new DisplayMetrics();
                display.getRealMetrics(metrics);
                put(item, "realMetrics", metrics(metrics));
                display.getMetrics(metrics);
                put(item, "appMetrics", metrics(metrics));
                Display.Mode mode = display.getMode();
                JSONObject modeInfo = new JSONObject();
                put(modeInfo, "id", mode.getModeId());
                put(modeInfo, "width", mode.getPhysicalWidth());
                put(modeInfo, "height", mode.getPhysicalHeight());
                put(modeInfo, "refreshRate", mode.getRefreshRate());
                put(item, "mode", modeInfo);
            } catch (Throwable failure) { put(item, "error", error(failure)); }
            result.put(item);
        }
        return result;
    }

    @SuppressWarnings("deprecation")
    private static JSONObject metrics(DisplayMetrics metrics) {
        JSONObject result = new JSONObject();
        put(result, "widthPixels", metrics.widthPixels);
        put(result, "heightPixels", metrics.heightPixels);
        put(result, "densityDpi", metrics.densityDpi);
        put(result, "density", metrics.density);
        put(result, "scaledDensity", metrics.scaledDensity);
        put(result, "xdpi", metrics.xdpi);
        put(result, "ydpi", metrics.ydpi);
        return result;
    }

    private JSONObject dumpDisplays() {
        return runProcess(new ProcessBuilder("/system/bin/dumpsys", "display"), 8);
    }

    private JSONObject appProcessProbe() {
        JSONObject result = new JSONObject();
        put(result, "readOnly", true);
        put(result, "expectedUid", Process.myUid());
        put(result, "note", "app_process is launched with this app's existing UID; no root, shell identity, permission grant, or target-app setter is requested");
        try {
            File jar = extractBridge();
            put(result, "bridgePath", jar.getAbsolutePath());
            put(result, "bridgeWritable", jar.canWrite());
            ProcessBuilder inspect = bridgeProcess(jar, "inspect");
            JSONObject inspection = runProcess(inspect, 12);
            put(result, "inspect", inspection);
            JSONObject bridgeReport = parseBridgeReport(inspection);
            if (bridgeReport != null) put(inspection, "report", bridgeReport);
            boolean ok = inspection.optInt("exitCode", -1) == 0
                    && bridgeReport != null && bridgeReport.optBoolean("ok", false);
            put(result, "inspectSucceeded", ok);
            if (ok) {
                JSONObject maps = runProcess(bridgeProcess(jar, "get", "com.google.android.apps.maps"), 12);
                put(result, "mapsRead", maps);
                JSONObject mapsReport = parseBridgeReport(maps);
                if (mapsReport != null) put(maps, "report", mapsReport);
                put(result, "mapsReadSucceeded", maps.optInt("exitCode", -1) == 0
                        && mapsReport != null && mapsReport.optBoolean("ok", false));
            }
        } catch (Throwable failure) { put(result, "error", error(failure)); }
        return result;
    }

    private File extractBridge() throws Exception {
        File directory = new File(getFilesDir(), "probe-bridge");
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IllegalStateException("Cannot create bridge directory");
        File target = new File(directory, "display-policy-bridge.jar");
        File pending = File.createTempFile("bridge-", ".jar", directory);
        try {
            try (InputStream input = getAssets().open("display-policy-bridge.jar");
                    FileOutputStream output = new FileOutputStream(pending)) {
                // Open first, revoke write permission before adding code, then use the existing fd.
                // Android 14 requires dynamically loaded code to be read-only.
                if (!pending.setReadOnly()) throw new IllegalStateException("Cannot mark bridge JAR read-only");
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                output.getFD().sync();
            }
            if (target.exists() && !target.delete()) throw new IllegalStateException("Cannot replace existing bridge JAR");
            if (!pending.renameTo(target)) throw new IllegalStateException("Cannot publish extracted bridge JAR");
            return target;
        } finally {
            if (pending.exists()) pending.delete();
        }
    }

    private static ProcessBuilder bridgeProcess(File jar, String... command) {
        // Commands originate only from the fixed inspect/get call sites above, never an Intent.
        String[] invocation = new String[3 + command.length];
        invocation[0] = "/system/bin/app_process";
        invocation[1] = "/system/bin";
        invocation[2] = "DisplayPolicyBridge";
        System.arraycopy(command, 0, invocation, 3, command.length);
        ProcessBuilder builder = new ProcessBuilder(invocation);
        builder.environment().put("CLASSPATH", jar.getAbsolutePath());
        return builder;
    }

    private static JSONObject parseBridgeReport(JSONObject process) {
        try { return new JSONObject(process.optString("stdout").trim()); }
        catch (Throwable failure) {
            put(process, "jsonParseError", error(failure));
            return null;
        }
    }

    private static JSONObject runProcess(ProcessBuilder builder, int timeoutSeconds) {
        JSONObject result = new JSONObject();
        java.lang.Process process = null;
        try {
            process = builder.start();
            process.getOutputStream().close();
            final BoundedDrain output = new BoundedDrain(process.getInputStream());
            final BoundedDrain errors = new BoundedDrain(process.getErrorStream());
            Thread outputThread = new Thread(output, "display-dump-output");
            Thread errorThread = new Thread(errors, "display-dump-errors");
            outputThread.start();
            errorThread.start();
            boolean finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS);
            put(result, "timedOut", !finished);
            if (!finished) process.destroyForcibly();
            outputThread.join(1500);
            errorThread.join(1500);
            if (finished) put(result, "exitCode", process.exitValue());
            put(result, "stdout", output.value());
            put(result, "stderr", errors.value());
            put(result, "stdoutTruncated", output.truncated);
            put(result, "stderrTruncated", errors.truncated);
            if (output.failure != null) put(result, "stdoutReadError", error(output.failure));
            if (errors.failure != null) put(result, "stderrReadError", error(errors.failure));
        } catch (Throwable failure) {
            put(result, "error", error(failure));
        } finally {
            if (process != null) process.destroy();
        }
        return result;
    }

    private static final class BoundedDrain implements Runnable {
        private final InputStream input;
        private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        volatile boolean truncated;
        volatile Throwable failure;
        BoundedDrain(InputStream input) { this.input = input; }
        @Override public void run() {
            try (InputStream stream = input) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = stream.read(buffer)) != -1) {
                    synchronized (bytes) {
                        int remaining = 1024 * 1024 - bytes.size();
                        if (count > remaining) truncated = true;
                        if (remaining > 0) bytes.write(buffer, 0, Math.min(count, remaining));
                    }
                }
            } catch (Throwable error) { failure = error; }
        }
        String value() {
            synchronized (bytes) { return new String(bytes.toByteArray(), StandardCharsets.UTF_8); }
        }
    }

    private static JSONArray methods(Method[] methods) {
        Arrays.sort(methods, Comparator.comparing(Method::toGenericString));
        JSONArray result = new JSONArray();
        for (Method method : methods) result.put(method.toGenericString());
        return result;
    }

    private static Object serialize(Object value, int depth, IdentityHashMap<Object, Boolean> seen) throws Exception {
        if (value == null) return JSONObject.NULL;
        if (value instanceof String || value instanceof Number || value instanceof Boolean) return value;
        if (value instanceof Character) return String.valueOf(value);
        if (value instanceof Enum<?>) return ((Enum<?>) value).name();
        JSONObject result = new JSONObject();
        Class<?> type = value.getClass();
        put(result, "class", type.getName());
        if (depth >= 5) { put(result, "depthLimit", true); return result; }
        if (seen.put(value, Boolean.TRUE) != null) { put(result, "repeatedReference", true); return result; }
        if (type.isArray()) {
            JSONArray items = new JSONArray();
            int length = Array.getLength(value);
            for (int i = 0; i < Math.min(length, 64); i++) items.put(serialize(Array.get(value, i), depth + 1, seen));
            put(result, "length", length);
            put(result, "items", items);
            put(result, "truncated", length > 64);
            return result;
        }
        JSONObject fields = new JSONObject();
        put(result, "fields", fields);
        int count = 0;
        for (Class<?> current = type; current != null && current != Object.class; current = current.getSuperclass()) {
            Field[] declared = current.getDeclaredFields();
            Arrays.sort(declared, Comparator.comparing(Field::getName));
            for (Field field : declared) {
                if (Modifier.isStatic(field.getModifiers()) || field.isSynthetic()) continue;
                if (++count > 64) { put(result, "truncated", true); return result; }
                String key = current == type ? field.getName() : current.getName() + "#" + field.getName();
                try {
                    field.setAccessible(true);
                    put(fields, key, serialize(field.get(value), depth + 1, seen));
                } catch (Throwable failure) { put(fields, key, new JSONObject().put("error", error(failure))); }
            }
        }
        return result;
    }

    private static JSONObject error(Throwable original) {
        Throwable failure = original;
        while (failure instanceof InvocationTargetException && ((InvocationTargetException) failure).getTargetException() != null) {
            failure = ((InvocationTargetException) failure).getTargetException();
        }
        JSONObject result = new JSONObject();
        put(result, "class", failure.getClass().getName());
        put(result, "message", failure.getMessage());
        JSONArray frames = new JSONArray();
        StackTraceElement[] stack = failure.getStackTrace();
        for (int i = 0; i < Math.min(8, stack.length); i++) frames.put(stack[i].toString());
        put(result, "stack", frames);
        return result;
    }

    private static void put(JSONObject object, String key, Object value) {
        try { object.put(key, value == null ? JSONObject.NULL : value); }
        catch (Exception failure) { throw new IllegalStateException("Cannot encode " + key, failure); }
    }

    private static String summary(JSONObject report) {
        StringBuilder text = new StringBuilder("Read-only probe completed.\n\n");
        JSONObject vendor = report.optJSONObject("vendorService");
        if (vendor != null) {
            text.append("Vendor service available: ").append(vendor.optBoolean("available")).append('\n');
            text.append("All three policy getters succeeded: ").append(vendor.optBoolean("probeSucceeded")).append('\n');
            if (vendor.has("error")) text.append(vendor.optJSONObject("error")).append('\n');
            JSONObject policies = vendor.optJSONObject("policies");
            if (policies != null) {
                for (String packageName : PACKAGES) {
                    text.append('\n').append(packageName).append('\n');
                    JSONObject policy = policies.optJSONObject(packageName);
                    JSONObject fields = policy == null ? null : policy.optJSONObject("fields");
                    if (fields != null) {
                        for (String name : new String[]{"appDpi", "appDpiScale", "isDpiSetting", "appTextEnhance"}) {
                            text.append(name).append(": ").append(fields.opt(name)).append('\n');
                        }
                    } else text.append(policy).append('\n');
                }
            }
        }
        JSONObject bridge = report.optJSONObject("appProcessProbe");
        if (bridge != null) {
            text.append("\nApp-process inspect succeeded: ").append(bridge.optBoolean("inspectSucceeded")).append('\n');
            text.append("App-process Maps read succeeded: ").append(bridge.optBoolean("mapsReadSucceeded")).append('\n');
            if (bridge.has("error")) text.append(bridge.optJSONObject("error")).append('\n');
        }
        JSONArray displays = report.optJSONArray("displays");
        text.append("\nVisible displays: ").append(displays == null ? 0 : displays.length()).append('\n');
        if (displays != null) {
            for (int i = 0; i < displays.length(); i++) {
                JSONObject display = displays.optJSONObject(i);
                if (display == null) continue;
                text.append("#").append(display.optInt("id")).append(' ').append(display.optString("name")).append('\n');
                text.append(display.optJSONObject("realMetrics")).append('\n');
            }
        }
        text.append("\nDUMP permission: ").append(report.optBoolean("dumpPermissionGranted")).append('\n');
        text.append("\nReport: ").append(report.optString("reportPath", "Could not save report")).append('\n');
        if (report.has("saveError")) text.append(report.optJSONObject("saveError")).append('\n');
        text.append("\nThe full JSON report is also logged with tag HBAutoScale.");
        return text.toString();
    }
}
