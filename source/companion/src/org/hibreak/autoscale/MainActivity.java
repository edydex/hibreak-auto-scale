package org.hibreak.autoscale;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.widget.*;
import org.json.JSONObject;

/** The only user controls: explicit enable, stop/restore, and status refresh. */
public final class MainActivity extends Activity {
    private static final String PICK_CAR = "pick-car";
    private final Handler handler = new Handler(android.os.Looper.getMainLooper());
    private TextView status;
    private String actionAfterNotification;
    private boolean exportInProgress;
    private final Runnable refresh = new Runnable() { public void run() { showStatus(); handler.postDelayed(this, 2000); } };
    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout root = new LinearLayout(this); root.setOrientation(1); root.setPadding(28, 28, 28, 28); root.setBackgroundColor(Color.WHITE);
        TextView title = new TextView(this); title.setText("HiBreak Auto Scale"); title.setTextSize(26); title.setTextColor(Color.BLACK); root.addView(title);
        TextView explanation = new TextView(this); explanation.setTextSize(17); explanation.setTextColor(Color.BLACK); explanation.setPadding(0, 16, 0, 16);
        explanation.setText("Choose your paired car once for automatic preparation as it connects. If projection starts before scaling is ready, a quick reconnect may still be needed.\n\nFirst use: enable detection to learn the car DPI. Manual Prepare remains a fallback. Phone settings restore after the car and projection disconnect."); root.addView(explanation);
        Button automatic = new Button(this); automatic.setText("Automatic for paired car"); automatic.setOnClickListener(v -> startWithNotifications(PICK_CAR)); root.addView(automatic);
        Button prepare = new Button(this); prepare.setText("Prepare for car"); prepare.setOnClickListener(v -> startWithNotifications(AutoScaleService.PREPARE)); root.addView(prepare);
        Button enable = new Button(this); enable.setText("Enable detection / learn car"); enable.setOnClickListener(v -> enable()); root.addView(enable);
        Button stop = new Button(this); stop.setText("Stop and restore"); stop.setOnClickListener(v -> send(AutoScaleService.STOP)); root.addView(stop);
        Button update = new Button(this); update.setText("Refresh status"); update.setOnClickListener(v -> { refreshServiceIfRunning(); showStatus(); }); root.addView(update);
        Button diagnostics = new Button(this); diagnostics.setText("Read-only diagnostics"); diagnostics.setOnClickListener(v -> startActivity(new Intent(this, ProbeActivity.class))); root.addView(diagnostics);
        Button export = new Button(this); export.setText("Export saved backup"); export.setOnClickListener(v -> exportBackup()); root.addView(export);
        TextView exportNote = new TextView(this); exportNote.setTextSize(15); exportNote.setTextColor(Color.BLACK);
        exportNote.setText("A backup export is a personal recovery file for this phone. Keep it private; it is not for restoring another phone."); root.addView(exportNote);
        ScrollView scroll = new ScrollView(this); status = new TextView(this); status.setTextSize(17); status.setTextColor(Color.BLACK); status.setTextIsSelectable(true); status.setPadding(0, 18, 0, 18); scroll.addView(status); root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root); showStatus();
    }
    private void enable() {
        startWithNotifications(AutoScaleService.ENABLE);
    }
    private void startWithNotifications(String action) {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) { actionAfterNotification = action; requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 100); return; }
        performPermittedAction(action);
    }
    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == 100 && actionAfterNotification != null) { String action = actionAfterNotification; actionAfterNotification = null; if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) performPermittedAction(action); else status.setText("Enable notifications before starting so the running status remains visible."); }
        if (requestCode == 102) { if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) choosePairedCar(); else status.setText("Nearby devices access is needed to recognize only the paired car you select. Manual preparation remains available."); }
    }
    private void performPermittedAction(String action) { if (PICK_CAR.equals(action)) choosePairedCar(); else send(action); }
    private void choosePairedCar() {
        if (Build.VERSION.SDK_INT >= 31 && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.BLUETOOTH_CONNECT}, 102); return;
        }
        try {
            android.bluetooth.BluetoothManager manager = (android.bluetooth.BluetoothManager)getSystemService(BLUETOOTH_SERVICE);
            android.bluetooth.BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
            if (adapter == null) throw new IllegalStateException("Bluetooth is not available");
            java.util.List<android.bluetooth.BluetoothDevice> choices = new java.util.ArrayList<android.bluetooth.BluetoothDevice>();
            for (android.bluetooth.BluetoothDevice device : adapter.getBondedDevices()) {
                int type = device.getType();
                if (type == android.bluetooth.BluetoothDevice.DEVICE_TYPE_CLASSIC || type == android.bluetooth.BluetoothDevice.DEVICE_TYPE_DUAL) choices.add(device);
            }
            choices.sort((a, b) -> pairedName(a).compareToIgnoreCase(pairedName(b)));
            if (choices.isEmpty()) {
                new AlertDialog.Builder(this).setTitle("Pair the car first").setMessage("No paired classic Bluetooth car/device is available. Pair your car in Android Bluetooth settings, then choose it here.")
                        .setPositiveButton("Bluetooth settings", (d, w) -> startActivity(new Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS))).setNegativeButton("Cancel", null).show();
                return;
            }
            String[] labels = new String[choices.size()];
            for (int i = 0; i < choices.size(); i++) {
                android.bluetooth.BluetoothDevice device = choices.get(i);
                String address = device.getAddress();
                labels[i] = pairedName(device) + " (" + address.substring(Math.max(0, address.length() - 5)) + ")";
            }
            new AlertDialog.Builder(this).setTitle("Choose your paired car").setItems(labels, (dialog, which) -> {
                android.bluetooth.BluetoothDevice device = choices.get(which);
                getSharedPreferences(BluetoothCarMonitor.CONFIG_NAME, MODE_PRIVATE).edit()
                        .putString(BluetoothCarMonitor.KEY_SELECTED_ADDRESS, device.getAddress())
                        .putString(AutoScaleService.KEY_SELECTED_LABEL, pairedName(device))
                        .putBoolean(AutoScaleService.KEY_AUTOMATIC_ENABLED, true).commit();
                send(AutoScaleService.AUTO_ENABLE);
            }).setNegativeButton("Cancel", null).show();
        } catch (Exception error) { new AlertDialog.Builder(this).setTitle("Could not choose car").setMessage(String.valueOf(error.getMessage())).setPositiveButton("OK", null).show(); }
    }
    private static String pairedName(android.bluetooth.BluetoothDevice device) {
        String name = device.getName(); return name == null || name.trim().isEmpty() ? "Paired device" : name;
    }
    private void send(String action) {
        Intent intent = new Intent(this, AutoScaleService.class).setAction(action);
        try { if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent); else startService(intent); }
        catch (Exception error) { status.setText("Could not start: " + error); }
    }
    private void refreshServiceIfRunning() {
        try { if (AutoScaleService.automaticEnabled(this) || StateStore.workNeeded(new StateStore(this).load())) send(AutoScaleService.REFRESH); }
        catch (Exception ignored) {}
    }
    private void showStatus() {
        if (exportInProgress) return;
        try {
            JSONObject state = new StateStore(this).load();
            String text = state.optString("status") + "\n\nAutomatic scaling: " + (state.optBoolean("enabled") ? "enabled" : "off");
            android.content.SharedPreferences car = getSharedPreferences(BluetoothCarMonitor.CONFIG_NAME, MODE_PRIVATE);
            text += "\nPaired-car automatic: " + (AutoScaleService.automaticEnabled(this) ? car.getString(AutoScaleService.KEY_SELECTED_LABEL, "selected car") : "off");
            if (AutoScaleService.automaticEnabled(this) && Build.VERSION.SDK_INT >= 31 && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) text += "\nNearby devices access is missing. Choose Automatic for paired car to grant it again.";
            text += "\nDisplay diagnostics permission: " + (checkSelfPermission(Manifest.permission.DUMP) == PackageManager.PERMISSION_GRANTED ? "granted" : "computer setup required");
            if (state.has("pending")) text += "\nFinishing or recovering a saved settings change. Your original settings are retained.";
            text += "\n\nYour original phone settings are saved here. Use Stop and restore before removing the app, clearing its storage, or removing display diagnostics access.";
            if (!text.contentEquals(status.getText())) status.setText(text);
        } catch (Exception error) { String text = "Cannot read saved status: " + error; if (!text.contentEquals(status.getText())) status.setText(text); }
    }
    private void exportBackup() {
        try {
            if (!new StateStore(this).load().has("backup")) {
                new AlertDialog.Builder(this).setTitle("No saved backup yet").setMessage("Disconnect Android Auto and enable automatic scaling to save your original phone settings first.").setPositiveButton("OK", null).show();
                return;
            }
            String date = new java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.US).format(new java.util.Date());
            Intent create = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/json")
                    .putExtra(Intent.EXTRA_TITLE, "HiBreak-saved-settings-" + date + ".json");
            startActivityForResult(create, 101);
        } catch (Exception error) { Toast.makeText(this, "Could not open backup export: " + error.getMessage(), Toast.LENGTH_LONG).show(); }
    }
    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != 101 || resultCode != RESULT_OK || data == null || data.getData() == null) return;
        final android.net.Uri destination = data.getData();
        exportInProgress = true;
        status.setText("Exporting your saved settings…");
        new Thread(() -> {
            String failure = null;
            try {
                // AtomicFile supplies one complete committed state snapshot. Export never
                // invokes the bridge, changes enabled state, or applies phone preferences.
                JSONObject snapshot = new StateStore(MainActivity.this).load();
                if (!snapshot.has("backup")) throw new java.io.IOException("Saved backup is no longer available");
                byte[] bytes = snapshot.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8);
                try (java.io.OutputStream output = getContentResolver().openOutputStream(destination, "w")) {
                    if (output == null) throw new java.io.IOException("The selected location is not writable");
                    output.write(bytes); output.flush();
                }
            } catch (Exception error) { failure = error.getMessage(); }
            final String result = failure;
            runOnUiThread(() -> {
                exportInProgress = false;
                if (isFinishing() || isDestroyed()) return;
                showStatus();
                new AlertDialog.Builder(MainActivity.this).setTitle(result == null ? "Backup saved" : "Backup could not be saved")
                        .setMessage(result == null ? "Keep this personal file private. It contains your saved phone settings and recovery history for this phone. It is not a backup to apply to another phone." : result)
                        .setPositiveButton("OK", null).show();
            });
        }, "HiBreak-backup-export").start();
    }
    @Override protected void onResume() { super.onResume(); handler.post(refresh); refreshServiceIfRunning(); }
    @Override protected void onPause() { handler.removeCallbacks(refresh); super.onPause(); }
}
