package org.hibreak.autoscale;

/** Clock/boot/host transition checks, without Android or phone access. */
public final class PreparationWindowTest {
    private static int checks;
    public static void main(String[] args) {
        expect(PreparationWindow.Decision.HOLD, true, false, 7, 7, 100, 600100, 101, "a", "a");
        expect(PreparationWindow.Decision.HOLD, true, false, 7, 7, 100, 600100, 600099, "a", "a");
        expect(PreparationWindow.Decision.RESTORE, true, false, 7, 7, 100, 600100, 600100, "a", "a");
        expect(PreparationWindow.Decision.RESTORE, true, false, 7, 7, 100, 600100, 99, "a", "a");
        expect(PreparationWindow.Decision.RESTORE, true, false, 7, 8, 100, 600100, 101, "a", "a");
        expect(PreparationWindow.Decision.HOLD, true, false, 7, 7, 100, 600100, 101, "a", "new-process");
        expect(PreparationWindow.Decision.RESTORE, false, false, 7, 7, 100, 600100, 101, "a", "a");
        expect(PreparationWindow.Decision.JOIN_HOST, true, true, 7, 7, 100, 600100, 101, "a", "a");
        expect(PreparationWindow.Decision.JOIN_HOST, true, true, 7, 8, 100, 600100, 700000, "a", "new");
        expect(PreparationWindow.Decision.JOIN_HOST, false, true, -1, -1, -1, -1, 50, "a", "new");
        expect(PreparationWindow.Decision.HOLD, true, false, -1, -1, 100, 600100, 101, "a", "a");
        expect(PreparationWindow.Decision.RESTORE, true, false, -1, -1, 100, 600100, 101, "a", "new");
        expect(PreparationWindow.Decision.RESTORE, true, false, -1, -1, 100, 600100, 101, null, "a");
        expect(PreparationWindow.Decision.RESTORE, true, false, 7, 7, 100, 100, 101, "a", "a");
        expect(PreparationWindow.Decision.RESTORE, true, false, 7, 7, -1, 600100, 101, "a", "a");
        System.out.println("PASS " + checks + " host-only preparation clock/boot/host transition checks; no phone access.");
    }
    private static void expect(PreparationWindow.Decision expected, boolean ready, boolean host, int savedBoot, int currentBoot,
            long created, long expires, long now, String savedProcess, String currentProcess) {
        PreparationWindow.Decision actual = PreparationWindow.evaluate(ready, host, savedBoot, currentBoot, created, expires, now, savedProcess, currentProcess);
        if (actual != expected) throw new AssertionError("Expected " + expected + " but got " + actual);
        checks++;
    }
}
