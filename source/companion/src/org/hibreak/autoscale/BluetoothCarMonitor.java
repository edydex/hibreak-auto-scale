package org.hibreak.autoscale;

import android.Manifest;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothA2dp;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothHeadset;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Watches only the explicitly selected bonded classic car. Construct with the
 * foreground service Context and close with that service. Listener callbacks
 * run on the main looper, never on the engine worker. No scanning or pairing.
 */
public final class BluetoothCarMonitor implements AutoCloseable {
    public static final String CONFIG_NAME = "car-trigger-config";
    public static final String KEY_SELECTED_ADDRESS = "selected_address";
    // EXTRA_TRANSPORT is absent from some public SDK revisions. Its platform
    // wire key is stable; missing means an older classic ACL broadcast.
    private static final String EXTRA_TRANSPORT = "android.bluetooth.device.extra.TRANSPORT";
    private static final int TRANSPORT_LE = 2;
    private static final long REFRESH_MILLIS = 10_000L;
    private static final long PROFILE_REQUEST_TIMEOUT_MILLIS = 15_000L;

    public interface Listener {
        void onCarSignal(boolean connectingOrConnected, String stage, long elapsedRealtimeMillis);
    }

    private final Context context;
    private final Listener listener;
    private final SharedPreferences preferences;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final CarSignalPolicy policy = new CarSignalPolicy();
    private final Map<Integer, BluetoothProfile> proxies = new HashMap<Integer, BluetoothProfile>();
    private final Set<Integer> pendingProfiles = new HashSet<Integer>();
    private final Map<Integer, Long> pendingAt = new HashMap<Integer, Long>();
    private final Map<Integer, Integer> profileRequests = new HashMap<Integer, Integer>();
    private BluetoothAdapter adapter;
    private BluetoothDevice selected;
    private String address = "";
    private boolean requested, running, preferencesRegistered;
    private int generation;
    private String status = "Car monitoring is off";

    public BluetoothCarMonitor(Context foregroundContext, Listener listener) {
        if (foregroundContext == null || listener == null) throw new IllegalArgumentException("Context and listener are required");
        this.context = foregroundContext;
        this.listener = listener;
        this.preferences = context.getSharedPreferences(CONFIG_NAME, Context.MODE_PRIVATE);
    }

    public synchronized boolean isRunning() { return running; }
    public synchronized boolean isCarActive() {
        expirePresence(SystemClock.elapsedRealtime());
        return policy.isFreshActive(SystemClock.elapsedRealtime());
    }
    public synchronized long getLastConfirmedActiveElapsedMillis() {
        return policy.getLastConfirmedActiveElapsedMillis();
    }
    public synchronized String getStatus() { return status; }

    /** Returns whether system-event monitoring is registered; it never changes DPI. */
    public synchronized boolean start() {
        requested = true;
        if (!preferencesRegistered) {
            preferences.registerOnSharedPreferenceChangeListener(preferenceListener);
            preferencesRegistered = true;
        }
        if (running && !hasConnectPermission()) { permissionLost(); return false; }
        if (running) return true;
        return startInternal();
    }

    /** Re-read a changed selected device without leaving stale callbacks live. */
    public synchronized void refreshSelection() {
        if (!requested) return;
        String next = configuredAddress();
        if (running && next.equals(address) && hasConnectPermission()) {
            expirePresence(SystemClock.elapsedRealtime());
            refreshProfiles();
            return;
        }
        boolean wasActive = policy.isActive();
        stopInternal();
        if (wasActive) postSignal(false, "selection-changed", generation, true);
        startInternal();
    }

    @Override public synchronized void close() {
        requested = false;
        if (preferencesRegistered) {
            preferences.unregisterOnSharedPreferenceChangeListener(preferenceListener);
            preferencesRegistered = false;
        }
        stopInternal();
        status = "Car monitoring is off";
        // Closing is lifecycle cleanup, not a fabricated car disconnect event.
    }

    public boolean hasConnectPermission() {
        String permission = Build.VERSION.SDK_INT >= 31
                ? Manifest.permission.BLUETOOTH_CONNECT : Manifest.permission.BLUETOOTH;
        return context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }

    private boolean startInternal() {
        address = configuredAddress();
        if (!hasConnectPermission()) { status = "Nearby devices permission is required"; return false; }
        if (!BluetoothAdapter.checkBluetoothAddress(address)) { status = "Select a bonded classic car first"; return false; }
        BluetoothManager manager = (BluetoothManager) context.getSystemService(Context.BLUETOOTH_SERVICE);
        if (manager == null) { status = "Bluetooth is unavailable"; return false; }
        try {
            if (!hasConnectPermission()) return false;
            adapter = manager.getAdapter();
            if (adapter == null) { status = "Bluetooth is unavailable"; return false; }
            IntentFilter filter = new IntentFilter();
            filter.addAction(BluetoothDevice.ACTION_ACL_CONNECTED);
            filter.addAction(BluetoothDevice.ACTION_ACL_DISCONNECTED);
            filter.addAction(BluetoothDevice.ACTION_BOND_STATE_CHANGED);
            filter.addAction(BluetoothHeadset.ACTION_CONNECTION_STATE_CHANGED);
            filter.addAction(BluetoothA2dp.ACTION_CONNECTION_STATE_CHANGED);
            filter.addAction(BluetoothAdapter.ACTION_CONNECTION_STATE_CHANGED);
            filter.addAction(BluetoothAdapter.ACTION_STATE_CHANGED);
            if (Build.VERSION.SDK_INT >= 33) {
                // Bluetooth broadcasts can originate from the privileged BT app,
                // rather than system UID. All accepted actions are platform ones.
                context.registerReceiver(receiver, filter, null, main, Context.RECEIVER_EXPORTED);
            } else context.registerReceiver(receiver, filter, null, main);
            running = true;
            policy.reset();
            status = "Waiting for the selected car";
            refreshProfiles();
            schedulePresenceCheck();
            return true;
        } catch (SecurityException denied) {
            permissionLost(); return false;
        } catch (RuntimeException unavailable) {
            stopInternal(); status = "Bluetooth monitoring could not start"; return false;
        }
    }

    private String configuredAddress() {
        String configured = preferences.getString(KEY_SELECTED_ADDRESS, "");
        return configured == null ? "" : configured.trim().toUpperCase(Locale.ROOT);
    }

    private final SharedPreferences.OnSharedPreferenceChangeListener preferenceListener =
            new SharedPreferences.OnSharedPreferenceChangeListener() {
        @Override public void onSharedPreferenceChanged(SharedPreferences prefs, String key) {
            if (KEY_SELECTED_ADDRESS.equals(key)) main.post(new Runnable() {
                @Override public void run() { refreshSelection(); }
            });
        }
    };

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context unused, Intent intent) {
            synchronized (BluetoothCarMonitor.this) { receive(intent); }
        }
    };

    private final Runnable presenceCheck = new Runnable() {
        @Override public void run() {
            synchronized (BluetoothCarMonitor.this) {
                if (!running) return;
                if (!hasConnectPermission()) { permissionLost(); return; }
                expirePresence(SystemClock.elapsedRealtime());
                refreshProfiles();
                schedulePresenceCheck();
            }
        }
    };

    private void schedulePresenceCheck() {
        main.removeCallbacks(presenceCheck);
        if (running) main.postDelayed(presenceCheck, REFRESH_MILLIS);
    }

    private void expirePresence(long at) {
        if (running && policy.isActive() && !policy.isFreshActive(at)) {
            notifyUpdate(policy.reset(), "car-presence-expired", at);
            status = "Selected car presence could not be refreshed";
        }
    }

    private void receive(Intent intent) {
        if (!running || intent == null) return;
        if (!hasConnectPermission()) { permissionLost(); return; }
        if (!configuredAddress().equals(address)) { refreshSelection(); return; }
        String action = intent.getAction();
        long at = SystemClock.elapsedRealtime();
        if (BluetoothAdapter.ACTION_STATE_CHANGED.equals(action)) {
            int state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR);
            if (state == BluetoothAdapter.STATE_OFF || state == BluetoothAdapter.STATE_TURNING_OFF) {
                generation++;
                notifyUpdate(policy.reset(), "adapter-off", at);
                selected = null; releaseProxies(); status = "Bluetooth is off";
            } else if (state == BluetoothAdapter.STATE_ON) refreshProfiles();
            return;
        }
        BluetoothDevice device = deviceExtra(intent);
        if (!matchesSelected(device)) return;
        if (BluetoothDevice.ACTION_BOND_STATE_CHANGED.equals(action)) {
            if (intent.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, BluetoothDevice.ERROR) == BluetoothDevice.BOND_NONE) {
                generation++;
                notifyUpdate(policy.reset(), "selected-car-unpaired", at);
                selected = null; releaseProxies(); status = "The selected car is no longer bonded";
            }
            return;
        }
        if (selected == null && !resolveSelected()) return;
        if (BluetoothDevice.ACTION_ACL_CONNECTED.equals(action) || BluetoothDevice.ACTION_ACL_DISCONNECTED.equals(action)) {
            if (intent.getIntExtra(EXTRA_TRANSPORT, 0) == TRANSPORT_LE) return;
            boolean connected = BluetoothDevice.ACTION_ACL_CONNECTED.equals(action);
            notifyUpdate(policy.accept(CarSignalPolicy.Source.ACL,
                    connected ? CarSignalPolicy.CONNECTED : CarSignalPolicy.DISCONNECTED, at),
                    connected ? "classic-acl-connected" : "classic-acl-disconnected", at);
            return;
        }
        CarSignalPolicy.Source source;
        String prefix;
        String extra;
        if (BluetoothHeadset.ACTION_CONNECTION_STATE_CHANGED.equals(action)) {
            source = CarSignalPolicy.Source.HEADSET; prefix = "headset"; extra = BluetoothProfile.EXTRA_STATE;
        } else if (BluetoothA2dp.ACTION_CONNECTION_STATE_CHANGED.equals(action)) {
            source = CarSignalPolicy.Source.A2DP; prefix = "a2dp"; extra = BluetoothProfile.EXTRA_STATE;
        } else if (BluetoothAdapter.ACTION_CONNECTION_STATE_CHANGED.equals(action)) {
            source = CarSignalPolicy.Source.ADAPTER; prefix = "adapter"; extra = BluetoothAdapter.EXTRA_CONNECTION_STATE;
        } else return;
        int state = intent.getIntExtra(extra, CarSignalPolicy.UNKNOWN);
        notifyUpdate(policy.accept(source, state, at), prefix + "-" + stateName(state), at);
    }

    @SuppressWarnings("deprecation")
    private BluetoothDevice deviceExtra(Intent intent) {
        if (Build.VERSION.SDK_INT >= 33) return intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice.class);
        Object value = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE);
        return value instanceof BluetoothDevice ? (BluetoothDevice) value : null;
    }

    private boolean matchesSelected(BluetoothDevice device) {
        if (device == null || !hasConnectPermission()) return false;
        try { return address.equalsIgnoreCase(device.getAddress()); }
        catch (SecurityException denied) { permissionLost(); return false; }
    }

    private boolean resolveSelected() {
        if (adapter == null || !hasConnectPermission()) return false;
        try {
            if (!hasConnectPermission() || !adapter.isEnabled()) { status = "Bluetooth is off"; return false; }
            if (!hasConnectPermission()) return false;
            Set<BluetoothDevice> bonded = adapter.getBondedDevices();
            if (bonded != null) for (BluetoothDevice device : bonded) {
                if (!hasConnectPermission()) return false;
                if (!address.equalsIgnoreCase(device.getAddress())) continue;
                if (!hasConnectPermission()) return false;
                int type = device.getType();
                if (type == BluetoothDevice.DEVICE_TYPE_CLASSIC || type == BluetoothDevice.DEVICE_TYPE_DUAL) {
                    selected = device; return true;
                }
                status = "The selected device is not a classic Bluetooth car"; return false;
            }
            selected = null; status = "The selected classic car must remain bonded"; return false;
        } catch (SecurityException denied) { permissionLost(); return false; }
        catch (RuntimeException unavailable) { status = "Bluetooth device state is unavailable"; return false; }
    }

    private void refreshProfiles() {
        if (!running || !hasConnectPermission() || !resolveSelected()) return;
        requestProfile(BluetoothProfile.HEADSET);
        requestProfile(BluetoothProfile.A2DP);
    }

    private void requestProfile(final int profile) {
        BluetoothProfile existing = proxies.get(profile);
        if (existing != null) { readCurrent(profile, existing); return; }
        long at = SystemClock.elapsedRealtime();
        if (pendingProfiles.contains(profile)) {
            Long started = pendingAt.get(profile);
            if (started != null && at >= started && at - started < PROFILE_REQUEST_TIMEOUT_MILLIS) return;
            pendingProfiles.remove(profile); pendingAt.remove(profile);
        }
        if (adapter == null || !hasConnectPermission()) return;
        final int requestGeneration = generation;
        final BluetoothAdapter requestAdapter = adapter;
        final int requestId = profileRequests.containsKey(profile) ? profileRequests.get(profile) + 1 : 1;
        profileRequests.put(profile, requestId);
        pendingProfiles.add(profile);
        pendingAt.put(profile, at);
        try {
            if (!hasConnectPermission() || !requestAdapter.getProfileProxy(context, new BluetoothProfile.ServiceListener() {
                @Override public void onServiceConnected(int connectedProfile, BluetoothProfile proxy) {
                    synchronized (BluetoothCarMonitor.this) {
                        if (!running || generation != requestGeneration
                                || !Integer.valueOf(requestId).equals(profileRequests.get(connectedProfile))) {
                            closeProxy(requestAdapter, connectedProfile, proxy); return;
                        }
                        pendingProfiles.remove(connectedProfile);
                        pendingAt.remove(connectedProfile);
                        BluetoothProfile previous = proxies.put(connectedProfile, proxy);
                        if (previous != null && previous != proxy) closeProxy(requestAdapter, connectedProfile, previous);
                        if (!hasConnectPermission()) { permissionLost(); return; }
                        readCurrent(connectedProfile, proxy);
                    }
                }
                @Override public void onServiceDisconnected(int disconnectedProfile) {
                    synchronized (BluetoothCarMonitor.this) {
                        if (generation != requestGeneration
                                || !Integer.valueOf(requestId).equals(profileRequests.get(disconnectedProfile))) return;
                        proxies.remove(disconnectedProfile); pendingProfiles.remove(disconnectedProfile); pendingAt.remove(disconnectedProfile);
                        // Proxy service death is not proof that the car detached.
                        // Genuine ACL/profile/adapter edges, plus engine timeout,
                        // resolve it rather than fabricating a disconnect here.
                    }
                }
            }, profile)) { pendingProfiles.remove(profile); pendingAt.remove(profile); }
        } catch (SecurityException denied) { pendingProfiles.remove(profile); pendingAt.remove(profile); permissionLost(); }
        catch (RuntimeException unavailable) { pendingProfiles.remove(profile); pendingAt.remove(profile); status = "A Bluetooth profile is temporarily unavailable"; }
    }

    private void readCurrent(int profile, BluetoothProfile proxy) {
        if (!running || selected == null || !hasConnectPermission()) return;
        try {
            int state = proxy.getConnectionState(selected);
            CarSignalPolicy.Source source = profile == BluetoothProfile.HEADSET
                    ? CarSignalPolicy.Source.HEADSET : CarSignalPolicy.Source.A2DP;
            String stage = (profile == BluetoothProfile.HEADSET ? "headset" : "a2dp") + "-startup-" + stateName(state);
            long at = SystemClock.elapsedRealtime();
            notifyUpdate(policy.accept(source, state, at), stage, at);
        } catch (SecurityException denied) { permissionLost(); }
        catch (RuntimeException unavailable) { status = "Selected car profile state is temporarily unavailable"; }
    }

    private void notifyUpdate(CarSignalPolicy.Update update, String stage, long at) {
        if (!update.changed) return;
        status = update.active ? "Selected car is connecting or connected" : "Selected car connection ended";
        postSignal(update.active, stage, generation, false, at);
    }

    private void postSignal(boolean active, String stage, int token, boolean allowStopped) {
        postSignal(active, stage, token, allowStopped, SystemClock.elapsedRealtime());
    }

    private void postSignal(final boolean active, final String stage, final int token,
            final boolean allowStopped, final long at) {
        main.post(new Runnable() {
            @Override public void run() {
                synchronized (BluetoothCarMonitor.this) {
                    if (generation != token || (!running && !allowStopped)) return;
                }
                Log.i("HBAutoPerf", "car-signal " + stage);
                listener.onCarSignal(active, stage, at);
            }
        });
    }

    private void permissionLost() {
        boolean wasActive = policy.isActive();
        stopInternal(); status = "Nearby devices permission is required";
        if (wasActive) postSignal(false, "permission-unavailable", generation, true);
    }

    private void stopInternal() {
        generation++;
        main.removeCallbacks(presenceCheck);
        if (running) {
            try { context.unregisterReceiver(receiver); } catch (IllegalArgumentException ignored) {}
        }
        running = false;
        releaseProxies(); selected = null; adapter = null;
        policy.reset();
    }

    private void releaseProxies() {
        BluetoothAdapter current = adapter;
        for (Map.Entry<Integer, BluetoothProfile> entry : proxies.entrySet()) closeProxy(current, entry.getKey(), entry.getValue());
        proxies.clear(); pendingProfiles.clear(); pendingAt.clear(); profileRequests.clear();
    }

    private void closeProxy(BluetoothAdapter target, int profile, BluetoothProfile proxy) {
        if (target == null || proxy == null || !hasConnectPermission()) return;
        try { target.closeProfileProxy(profile, proxy); }
        catch (RuntimeException unavailable) { /* Cleanup only; no device identifiers logged. */ }
    }

    private static String stateName(int state) {
        switch (state) {
            case CarSignalPolicy.CONNECTING: return "connecting";
            case CarSignalPolicy.CONNECTED: return "connected";
            case CarSignalPolicy.DISCONNECTING: return "disconnecting";
            case CarSignalPolicy.DISCONNECTED: return "disconnected";
            default: return "unknown";
        }
    }
}
