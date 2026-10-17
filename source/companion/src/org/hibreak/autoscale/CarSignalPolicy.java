package org.hibreak.autoscale;

import java.util.EnumMap;

/** Pure selected-classic-device signal aggregation; no Android dependencies. */
public final class CarSignalPolicy {
    public enum Source { ACL, HEADSET, A2DP, ADAPTER }
    public static final int UNKNOWN = -1;
    public static final int DISCONNECTED = 0;
    public static final int CONNECTING = 1;
    public static final int CONNECTED = 2;
    public static final int DISCONNECTING = 3;
    public static final long PRESENCE_FRESHNESS_MILLIS = 60_000L;

    public static final class Update {
        public final boolean changed;
        public final boolean active;
        public final boolean accepted;
        private Update(boolean changed, boolean active, boolean accepted) {
            this.changed = changed; this.active = active; this.accepted = accepted;
        }
    }

    private final EnumMap<Source, Integer> states = new EnumMap<Source, Integer>(Source.class);
    private final EnumMap<Source, Long> times = new EnumMap<Source, Long>(Source.class);
    private boolean active;
    private boolean explicitlyAclDown;
    private boolean reconnectAttempt;
    private long aclDownAt = Long.MIN_VALUE;
    private long lastConfirmedActiveAt = Long.MIN_VALUE;

    public CarSignalPolicy() { clearState(); }

    public synchronized boolean isActive() { return active; }
    public synchronized long getLastConfirmedActiveElapsedMillis() {
        return lastConfirmedActiveAt == Long.MIN_VALUE ? -1 : lastConfirmedActiveAt;
    }
    public synchronized boolean isFreshActive(long now) {
        return active && lastConfirmedActiveAt >= 0 && now >= lastConfirmedActiveAt
                && now - lastConfirmedActiveAt <= PRESENCE_FRESHNESS_MILLIS;
    }

    public synchronized Update accept(Source source, int state, long elapsedMillis) {
        if (source == null || state < UNKNOWN || state > DISCONNECTING
                || elapsedMillis < 0 || elapsedMillis < times.get(source)) {
            return new Update(false, active, false);
        }
        if (source != Source.ACL && elapsedMillis < aclDownAt) {
            return new Update(false, active, false);
        }
        boolean previous = active;
        if (source == Source.ACL && state == DISCONNECTED) {
            // Physical classic ACL loss ends this connection epoch. Older HFP,
            // A2DP or adapter positives must not keep a departed car alive.
            for (Source value : Source.values()) {
                states.put(value, DISCONNECTED);
                times.put(value, Math.max(times.get(value), elapsedMillis));
            }
            explicitlyAclDown = true;
            reconnectAttempt = false;
            aclDownAt = elapsedMillis;
        } else {
            // A late CONNECTED/profile-proxy snapshot from the old epoch must
            // not resurrect it. A fresh CONNECTING edge or classic ACL connection
            // starts the next epoch; startup snapshots remain useful otherwise.
            if (source != Source.ACL && explicitlyAclDown && state == CONNECTED && !reconnectAttempt) {
                return new Update(false, active, false);
            }
            if (state == CONNECTING) reconnectAttempt = true;
            if (source == Source.ACL && state == CONNECTED) {
                explicitlyAclDown = false;
                reconnectAttempt = false;
            }
            states.put(source, state);
            times.put(source, elapsedMillis);
            if (state == CONNECTING || state == CONNECTED) lastConfirmedActiveAt = elapsedMillis;
        }
        active = false;
        for (int current : states.values()) {
            if (current == CONNECTING || current == CONNECTED) { active = true; break; }
        }
        return new Update(previous != active, active, true);
    }

    /** Adapter-off/selection reset. The engine, not this class, owns detach grace. */
    public synchronized Update reset() {
        boolean wasActive = active;
        clearState();
        return new Update(wasActive, false, true);
    }

    private void clearState() {
        for (Source source : Source.values()) {
            states.put(source, UNKNOWN);
            times.put(source, Long.MIN_VALUE);
        }
        active = false; explicitlyAclDown = false; reconnectAttempt = false;
        aclDownAt = Long.MIN_VALUE;
        lastConfirmedActiveAt = Long.MIN_VALUE;
    }
}
