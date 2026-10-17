package org.hibreak.autoscale;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.concurrent.*;

/** Fixed commands only. The child always retains this app's Linux UID. */
final class BridgeClient {
    static final String[] PACKAGES = {"com.google.android.projection.gearhead", "com.google.android.apps.maps", "com.google.android.googlequicksearchbox"};
    private final Context context;
    private volatile RpcProcess rpc;
    BridgeClient(Context context) { this.context = context; }

    synchronized File jar() throws Exception {
        File dir = new File(context.getFilesDir(), "automatic-bridge");
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("Cannot create bridge directory");
        String stamp = String.valueOf(context.getPackageManager().getPackageInfo(context.getPackageName(), 0).lastUpdateTime);
        File jar = new File(dir, "bridge.jar"), marker = new File(dir, "version");
        if (jar.isFile() && marker.isFile() && read(marker).equals(stamp) && !jar.canWrite()) return jar;
        File pending = File.createTempFile("code-", ".jar", dir);
        try {
            try (InputStream in = context.getAssets().open("display-policy-bridge.jar"); FileOutputStream out = new FileOutputStream(pending)) {
                if (!pending.setReadOnly()) throw new IOException("Cannot protect bridge code");
                byte[] b = new byte[8192]; int n;
                while ((n = in.read(b)) != -1) out.write(b, 0, n);
                out.getFD().sync();
            }
            if (jar.exists() && !jar.delete()) throw new IOException("Cannot replace bridge code");
            if (!pending.renameTo(jar)) throw new IOException("Cannot install private bridge code");
            try (FileOutputStream out = new FileOutputStream(marker)) { out.write(stamp.getBytes(StandardCharsets.UTF_8)); out.getFD().sync(); }
            return jar;
        } finally { if (pending.exists()) pending.delete(); }
    }

    JSONObject inspect() throws Exception { return call("inspect", null, null, true); }
    JSONObject get(String pkg) throws Exception {
        JSONObject report = call("get", pkg, null, true);
        return new JSONObject(report.getJSONObject("value").getJSONObject("fields").toString());
    }
    JSONObject write(String pkg, String field, int value) throws Exception {
        if ("appDpi".equals(field)) {
            if (value < 0 || value > 1000) throw new IOException("DPI outside restore/tool bounds");
            return call("set-dpi", pkg, value, false);
        }
        if ("isDpiSetting".equals(field) && (value == 0 || value == 1)) return call("set-dpi-enabled", pkg, value, false);
        throw new IOException("Unsupported automatic write field/value");
    }
    private synchronized JSONObject call(String command, String pkg, Integer value, boolean requireOk) throws Exception {
        long started = android.os.SystemClock.elapsedRealtime();
        boolean warm = rpc != null && rpc.process.isAlive();
        boolean ok = false;
        try {
            JSONObject result = callInternal(command, pkg, value, requireOk);
            ok = result.optBoolean("ok");
            return result;
        } finally {
            android.util.Log.i("HBAutoPerf", "rpc command=" + command + " durationMs=" + (android.os.SystemClock.elapsedRealtime() - started)
                    + " warm=" + warm + " ok=" + ok);
        }
    }
    private JSONObject callInternal(String command, String pkg, Integer value, boolean requireOk) throws Exception {
        if (pkg != null && !allowed(pkg)) throw new IOException("Package outside fixed allowlist");
        if (rpc == null || !rpc.process.isAlive()) {
            close();
            ProcessBuilder builder = new ProcessBuilder("/system/bin/app_process", "/system/bin", "DisplayPolicyBridge", "serve");
            builder.environment().put("CLASSPATH", jar().getAbsolutePath());
            RpcProcess starting = new RpcProcess(builder);
            try {
                JSONObject ready = starting.read(15);
                if (!ready.optBoolean("ready") || ready.optInt("bridgeVersion") < 3 || ready.optInt("uid", -1) != android.os.Process.myUid()) throw new IOException("Bridge server identity/protocol mismatch");
                rpc = starting;
            } catch (Exception failure) { starting.close(); throw failure; }
        }
        JSONObject request = new JSONObject().put("command", command);
        if (pkg != null) request.put("package", pkg);
        if (value != null) request.put("value", value);
        RpcProcess server = rpc;
        JSONObject report;
        try {
            server.output.write(request.toString()); server.output.newLine(); server.output.flush();
            report = server.read(15);
        } catch (Exception failure) { close(); throw failure; }
        if (report.optInt("uid", -1) != android.os.Process.myUid()) throw new IOException("Bridge identity differs from app UID");
        if (requireOk && !report.optBoolean("ok")) throw new IOException("Bridge refused: " + report.optJSONObject("error"));
        return report;
    }
    void close() {
        RpcProcess old = rpc; rpc = null;
        if (old != null) old.close();
    }
    private static final class RpcProcess {
        final java.lang.Process process;
        final BufferedWriter output;
        final BufferedReader input;
        final Drain errors;
        final ExecutorService reader;
        RpcProcess(ProcessBuilder builder) throws Exception {
            process = builder.start();
            output = new BufferedWriter(new OutputStreamWriter(process.getOutputStream(), StandardCharsets.UTF_8));
            input = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8));
            errors = new Drain(process.getErrorStream());
            Thread stderr = new Thread(errors, "HiBreak-bridge-stderr"); stderr.setDaemon(true); stderr.start();
            reader = Executors.newSingleThreadExecutor(new ThreadFactory() {
                public Thread newThread(Runnable task) { Thread thread = new Thread(task, "HiBreak-bridge-response"); thread.setDaemon(true); return thread; }
            });
        }
        JSONObject read(int seconds) throws Exception {
            Future<String> response = reader.submit(new Callable<String>() { public String call() throws Exception { return input.readLine(); } });
            String line;
            try { line = response.get(seconds, TimeUnit.SECONDS); }
            catch (Exception failure) { response.cancel(true); throw new IOException("Bridge response interrupted/timed out: " + errors.value(), failure); }
            if (line == null) throw new IOException("Bridge server closed: " + errors.value());
            if (line.length() > 1024 * 1024) throw new IOException("Bridge response exceeded bounded output");
            return new JSONObject(line);
        }
        void close() {
            process.destroyForcibly();
            reader.shutdownNow();
            try { output.close(); } catch (IOException ignored) {}
            try { input.close(); } catch (IOException ignored) {}
        }
    }
    String displayDump() throws Exception { return fixedDump("display"); }
    String policyDump() throws Exception { return fixedDump("xrz_display_policy_service"); }
    private String fixedDump(String service) throws Exception {
        long started = android.os.SystemClock.elapsedRealtime();
        boolean ok = false;
        try {
            Result r = run(new ProcessBuilder("/system/bin/dumpsys", service), 8);
            if (r.exit != 0 || r.stdout.contains("Permission Denial") || r.truncated) throw new IOException("Display diagnostics unavailable: " + r.description());
            ok = true;
            return r.stdout;
        } finally {
            android.util.Log.i("HBAutoPerf", "dump service=" + service + " durationMs=" + (android.os.SystemClock.elapsedRealtime() - started) + " ok=" + ok);
        }
    }
    int physicalDpi() throws Exception {
        Result r = run(new ProcessBuilder("/system/bin/getprop", "ro.sf.lcd_density"), 4);
        int dpi = Integer.parseInt(r.stdout.trim());
        if (r.exit != 0 || dpi < 1 || dpi > 1000) throw new IOException("Invalid physical DPI property");
        return dpi;
    }
    static boolean allowed(String pkg) { for (String item : PACKAGES) if (item.equals(pkg)) return true; return false; }
    static String read(File file) throws Exception {
        try (InputStream in = new FileInputStream(file)) { ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] b = new byte[8192]; int n; while ((n = in.read(b)) != -1) out.write(b, 0, n); return new String(out.toByteArray(), StandardCharsets.UTF_8); }
    }
    static final class Result {
        final int exit; final String stdout, stderr; final boolean truncated;
        Result(int exit, Drain out, Drain err) { this.exit = exit; stdout = out.value(); stderr = err.value(); truncated = out.truncated || err.truncated; }
        String description() { return "exit=" + exit + ", stderr=" + stderr + ", truncated=" + truncated; }
    }
    private static final class Drain implements Runnable {
        final InputStream in; final ByteArrayOutputStream bytes = new ByteArrayOutputStream(); volatile boolean truncated;
        Drain(InputStream in) { this.in = in; }
        public void run() { try (InputStream input = in) { byte[] b = new byte[8192]; int n; while ((n = input.read(b)) != -1) synchronized (bytes) { int left = 1024 * 1024 - bytes.size(); if (n > left) truncated = true; if (left > 0) bytes.write(b, 0, Math.min(left, n)); } } catch (IOException ignored) {} }
        String value() { synchronized (bytes) { return new String(bytes.toByteArray(), StandardCharsets.UTF_8); } }
    }
    static Result run(ProcessBuilder builder, int seconds) throws Exception {
        java.lang.Process process = builder.start();
        try {
            process.getOutputStream().close();
            Drain out = new Drain(process.getInputStream()), err = new Drain(process.getErrorStream());
            Thread a = new Thread(out), b = new Thread(err); a.start(); b.start();
            boolean finished = process.waitFor(seconds, TimeUnit.SECONDS);
            if (!finished) process.destroyForcibly();
            a.join(1500); b.join(1500);
            if (!finished) throw new IOException("Command timed out after " + seconds + " seconds");
            Result result = new Result(process.exitValue(), out, err);
            if (result.truncated) throw new IOException("Command exceeded bounded output");
            return result;
        } finally { process.destroy(); }
    }
}
