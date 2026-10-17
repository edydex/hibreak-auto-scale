package org.hibreak.autoscale;

import android.app.*;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.hardware.display.DisplayManager;
import android.os.*;
import java.util.concurrent.*;

/** One serialized worker; display callbacks schedule an immediate fresh dump. */
public final class AutoScaleService extends Service implements DisplayManager.DisplayListener {
    static final String ENABLE = "org.hibreak.autoscale.ENABLE";
    static final String STOP = "org.hibreak.autoscale.STOP";
    static final String REFRESH = "org.hibreak.autoscale.REFRESH";
    static final String PREPARE = "org.hibreak.autoscale.PREPARE";
    static final String AUTO_ENABLE = "org.hibreak.autoscale.AUTO_ENABLE";
    static final String KEY_AUTOMATIC_ENABLED = "automatic_enabled";
    static final String KEY_SELECTED_LABEL = "selected_label";
    private static final String CHANNEL = "automatic-scaling";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private ScaleEngine engine;
    private boolean busy, refreshPending;
    private boolean notificationRefreshPending;
    private String lastNotificationText;
    private String requested;
    private DisplayManager displays;
    private BluetoothCarMonitor carMonitor;
    private boolean carActive, carArmPending;
    private int monitorGeneration;
    private final Runnable poll = new Runnable() { public void run() { runOne(); } };
    @Override public void onCreate() {
        super.onCreate();
        NotificationManager manager = (NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Automatic Android Auto scaling", NotificationManager.IMPORTANCE_LOW));
        Notification notification = notification("Starting saved-state recovery and display checks…");
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(1, notification);
        displays = (DisplayManager)getSystemService(DISPLAY_SERVICE);
        if (displays != null) displays.registerDisplayListener(this, main);
        if (automaticEnabled(this)) startCarMonitor();
    }
    @Override public int onStartCommand(Intent intent, int flags, int id) {
        String action = intent == null ? null : intent.getAction();
        if (REFRESH.equals(action) || ENABLE.equals(action) || AUTO_ENABLE.equals(action)) notificationRefreshPending = true;
        if (STOP.equals(action)) {
            getSharedPreferences(BluetoothCarMonitor.CONFIG_NAME, MODE_PRIVATE).edit().putBoolean(KEY_AUTOMATIC_ENABLED, false).commit();
            closeCarMonitor(); carActive = false; carArmPending = false;
        } else if (AUTO_ENABLE.equals(action)) startCarMonitor();
        if (ENABLE.equals(action) || STOP.equals(action) || PREPARE.equals(action) || AUTO_ENABLE.equals(action)) requested = action;
        schedule(0);
        return START_STICKY;
    }
    private void schedule(long delay) {
        main.removeCallbacks(poll);
        if (busy) { refreshPending = true; return; }
        main.postDelayed(poll, delay);
    }
    private void runOne() {
        if (busy) { refreshPending = true; return; }
        busy = true;
        final String action = requested; requested = null;
        final boolean forceNotificationRefresh = notificationRefreshPending; notificationRefreshPending = false;
        boolean freshCarActive = automaticEnabled(this) && carMonitor != null && carMonitor.isRunning() && carMonitor.isCarActive();
        if (freshCarActive && !carActive) carArmPending = true;
        carActive = freshCarActive;
        final boolean selectedCarActive = freshCarActive;
        final boolean armCar = carArmPending; carArmPending = false;
        worker.execute(new Runnable() {
            public void run() {
                try {
                    if (engine == null) engine = new ScaleEngine(AutoScaleService.this);
                    engine.setAutomaticCarActive(automaticEnabled(AutoScaleService.this) && selectedCarActive);
                    if (automaticEnabled(AutoScaleService.this) && (AUTO_ENABLE.equals(action) || !engine.enabled())) engine.enableAutomaticMode();
                    if (ENABLE.equals(action)) engine.enable();
                    if (PREPARE.equals(action)) engine.prepareForCar();
                    if (armCar && automaticEnabled(AutoScaleService.this)) engine.prepareAutomaticallyIfIdle();
                    if (STOP.equals(action)) engine.stopAndRestore();
                    else engine.tick();
                } catch (Throwable error) {
                    if (engine != null) engine.failure(error);
                    else try { StateStore store = new StateStore(AutoScaleService.this); org.json.JSONObject state = store.load(); state.put("status", "Needs attention: " + error); store.save(state); } catch (Exception ignored) {}
                }
                main.post(new Runnable() {
                    public void run() {
                        busy = false;
                        String text = engine == null ? "Saved state could not be loaded. Open the app." : engine.status();
                        if (shouldPostNotification(lastNotificationText, text, forceNotificationRefresh)) {
                            ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(1, notification(text));
                            lastNotificationText = text;
                        }
                        boolean needs = (engine != null && engine.needsWork()) || automaticEnabled(AutoScaleService.this);
                        if (!needs && requested == null) { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); return; }
                        boolean again = refreshPending || requested != null || carArmPending; refreshPending = false;
                        schedule(again ? 0 : engine != null && engine.connected() ? 2000 : 30000);
                    }
                });
            }
        });
    }
    static boolean automaticEnabled(android.content.Context context) {
        return context.getSharedPreferences(BluetoothCarMonitor.CONFIG_NAME, MODE_PRIVATE).getBoolean(KEY_AUTOMATIC_ENABLED, false);
    }
    static boolean shouldPostNotification(String previous, String current, boolean force) {
        return force || !current.equals(previous);
    }
    private void startCarMonitor() {
        closeCarMonitor();
        carActive = false; carArmPending = false;
        if (!automaticEnabled(this)) return;
        final int generation = ++monitorGeneration;
        carMonitor = new BluetoothCarMonitor(this, new BluetoothCarMonitor.Listener() {
            public void onCarSignal(final boolean active, final String stage, final long elapsedMillis) {
                main.post(new Runnable() { public void run() {
                    if (generation != monitorGeneration || !automaticEnabled(AutoScaleService.this)) return;
                    boolean previous = carActive; carActive = active;
                    if (active && !previous) carArmPending = true;
                    android.util.Log.i("HBAutoPerf", "car-signal active=" + active + " stage=" + stage + " eventElapsedMs=" + elapsedMillis);
                    schedule(0);
                }});
            }
        });
        boolean running = carMonitor.start();
        android.util.Log.i("HBAutoPerf", "car-monitor running=" + running);
    }
    private void closeCarMonitor() {
        monitorGeneration++;
        if (carMonitor != null) { carMonitor.close(); carMonitor = null; }
    }
    private Notification notification(String text) {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent content = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, AutoScaleService.class).setAction(STOP), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_manage).setContentTitle("HiBreak Auto Scale")
                .setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text)).setContentIntent(content).setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "Stop and restore", stop).build()).build();
    }
    public void onDisplayAdded(int id) { schedule(0); }
    public void onDisplayRemoved(int id) { schedule(0); }
    public void onDisplayChanged(int id) { schedule(0); }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onDestroy() { closeCarMonitor(); main.removeCallbacksAndMessages(null); if (displays != null) displays.unregisterDisplayListener(this); worker.shutdownNow(); if (engine != null) engine.close(); super.onDestroy(); }
}
