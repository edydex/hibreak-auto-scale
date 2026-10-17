package org.hibreak.autoscale;

import org.json.JSONObject;

/** Runs the production idle-transition and notification predicates, without Android services. */
public final class IdleUpdatesTest {
    private static int checks;
    public static void main(String[] args) throws Exception {
        String waiting = "Automatic scaling is enabled. Waiting for Android Auto.";
        for (boolean hostApplied : new boolean[]{false, true}) {
            for (boolean reconnectNeeded : new boolean[]{false, true}) {
                for (boolean sameStatus : new boolean[]{false, true}) {
                    Object backup = new Object(), ownership = new Object(), recovery = new Object();
                    JSONObject state = new JSONObject().put("hostApplied", hostApplied).put("reconnectNeeded", reconnectNeeded)
                            .put("status", sameStatus ? waiting : "Previous session")
                            .put("backup", backup).put("owned", ownership).put("pending", recovery);
                    int saves = 0;
                    for (int tick = 0; tick < 60; tick++) if (ScaleEngine.updateIdleState(state, waiting)) saves++;
                    check(saves == (hostApplied || reconnectNeeded || !sameStatus ? 1 : 0), "only the initial flag/status transition requests a save");
                    check(Boolean.FALSE.equals(state.get("hostApplied")) && Boolean.FALSE.equals(state.get("reconnectNeeded")), "both idle flags clear");
                    check(waiting.equals(state.getString("status")), "waiting status is current");
                    check(state.get("backup") == backup && state.get("owned") == ownership && state.get("pending") == recovery, "backup/ownership/recovery data untouched");
                    check(state.length() == 6, "no extra state fields created");
                }
            }
        }
        JSONObject state = new JSONObject().put("hostApplied", false).put("reconnectNeeded", false).put("status", waiting);
        String warning = waiting + " External edits preserved: Maps DPI";
        check(ScaleEngine.updateIdleState(state, warning), "new restore warning requests persistence");
        check(!ScaleEngine.updateIdleState(state, warning), "unchanged warning does not repeat persistence");
        state.put("hostApplied", true);
        check(ScaleEngine.updateIdleState(state, warning), "later host flag transition is persisted even with identical status");
        state.put("reconnectNeeded", true);
        check(ScaleEngine.updateIdleState(state, warning), "later reconnect flag transition is persisted even with identical status");

        check(AutoScaleService.shouldPostNotification(null, waiting, false), "first service status is published");
        for (int i = 0; i < 60; i++) check(!AutoScaleService.shouldPostNotification(waiting, waiting, false), "unchanged polling does not repost");
        check(AutoScaleService.shouldPostNotification(waiting, waiting, true), "explicit Refresh/resume can republish after unhide");
        check(AutoScaleService.shouldPostNotification(waiting, "Preparing", false), "preparation transition publishes");
        check(AutoScaleService.shouldPostNotification("Preparing", "Needs attention", false), "error transition publishes");
        check(AutoScaleService.shouldPostNotification("Ready", "Restoring", false), "restoration transition publishes");
        check(!AutoScaleService.shouldPostNotification("Restoring", "Restoring", false), "restoration status is deduplicated only while identical");
        System.out.println("PASS " + checks + " host-only idle persistence and notification transition checks; no phone access.");
    }
    private static void check(boolean okay, String detail) { if (!okay) throw new AssertionError(detail); checks++; }
}
