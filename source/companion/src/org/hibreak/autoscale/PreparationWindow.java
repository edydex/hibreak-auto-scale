package org.hibreak.autoscale;

/** Pure clock/lifecycle decision, kept separate for host-only transition tests. */
final class PreparationWindow {
    enum Decision { JOIN_HOST, HOLD, RESTORE }
    static Decision evaluate(boolean ready, boolean anyAaDisplay, int savedBoot, int currentBoot,
            long preparedAt, long expiresAt, long now, String savedProcess, String currentProcess) {
        if (anyAaDisplay) return Decision.JOIN_HOST;
        if (!ready) return Decision.RESTORE;
        if (savedBoot >= 0 && currentBoot >= 0) {
            if (savedBoot != currentBoot) return Decision.RESTORE;
        } else if (savedProcess == null || !savedProcess.equals(currentProcess)) return Decision.RESTORE;
        if (preparedAt < 0 || expiresAt <= preparedAt || now < preparedAt || now >= expiresAt) return Decision.RESTORE;
        return Decision.HOLD;
    }
}
