import org.hibreak.autoscale.CarSignalPolicy;

/** Synthetic signal-state tests only. No Android, radios, or selected devices. */
public final class CarSignalPolicyTest {
    private static int checks;
    private static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    private static CarSignalPolicy.Update event(CarSignalPolicy policy, CarSignalPolicy.Source source, int state, long at) {
        return policy.accept(source, state, at);
    }
    public static void main(String[] args) {
        CarSignalPolicy policy = new CarSignalPolicy();
        check(!policy.isActive(), "Starts inactive");
        CarSignalPolicy.Update early = event(policy, CarSignalPolicy.Source.HEADSET, 1, 10);
        check(early.changed && early.active && early.accepted, "HFP CONNECTING is an early edge");
        check(!event(policy, CarSignalPolicy.Source.HEADSET, 2, 11).changed, "CONNECTING to CONNECTED does not rearm");
        check(!event(policy, CarSignalPolicy.Source.A2DP, 2, 12).changed, "Second profile does not duplicate edge");
        check(!event(policy, CarSignalPolicy.Source.ACL, 2, 13).changed, "ACL after profile does not duplicate edge");
        check(!event(policy, CarSignalPolicy.Source.HEADSET, 0, 14).changed && policy.isActive(), "A2DP/ACL hold during HFP drop");
        check(!event(policy, CarSignalPolicy.Source.ADAPTER, 0, 15).changed && policy.isActive(), "Adapter disagreement does not erase live ACL");
        CarSignalPolicy.Update detached = event(policy, CarSignalPolicy.Source.ACL, 0, 16);
        check(detached.changed && !detached.active, "Physical classic ACL loss ends stale profile epoch");
        check(!event(policy, CarSignalPolicy.Source.A2DP, 2, 17).accepted && !policy.isActive(), "Late CONNECTED snapshot cannot resurrect old epoch");
        check(!event(policy, CarSignalPolicy.Source.HEADSET, 1, 15).accepted, "Older event cannot cross disconnect barrier");
        check(event(policy, CarSignalPolicy.Source.HEADSET, 1, 18).changed && policy.isActive(), "Fresh CONNECTING rearms immediately");
        check(!event(policy, CarSignalPolicy.Source.A2DP, 0, 19).changed && policy.isActive(), "Late other-profile down cannot erase new attempt");
        check(!event(policy, CarSignalPolicy.Source.ACL, 2, 20).changed, "New ACL confirms reconnected epoch");
        check(policy.reset().changed && !policy.isActive(), "Adapter-off/selection reset emits one inactive edge");
        check(!policy.reset().changed, "Duplicate reset is suppressed");
        check(event(policy, CarSignalPolicy.Source.A2DP, 2, 30).changed, "Already-connected startup profile works after reset");
        check(!event(policy, CarSignalPolicy.Source.A2DP, 2, 31).changed, "Repeated startup query is suppressed");
        check(!event(policy, CarSignalPolicy.Source.A2DP, 0, 29).accepted && policy.isActive(), "Stale per-source snapshot ignored");
        check(event(policy, CarSignalPolicy.Source.A2DP, 3, 32).changed && !policy.isActive(), "Disconnecting final profile withdraws connection hint");
        check(!event(policy, CarSignalPolicy.Source.HEADSET, 99, 33).accepted, "Invalid states ignored");
        check(!event(policy, null, 2, 34).accepted, "Null sources ignored");
        check(!event(policy, CarSignalPolicy.Source.HEADSET, 2, -1).accepted, "Invalid elapsed time ignored");
        CarSignalPolicy second = new CarSignalPolicy();
        check(event(second, CarSignalPolicy.Source.ADAPTER, 1, 100).changed, "Adapter CONNECTING starts hint");
        check(!event(second, CarSignalPolicy.Source.HEADSET, 0, 101).changed && second.isActive(), "Unrelated profile disconnected does not cancel early adapter hint");
        check(event(second, CarSignalPolicy.Source.ADAPTER, 0, 102).changed && !second.isActive(), "Failed adapter attempt cancels hint");
        CarSignalPolicy freshness = new CarSignalPolicy();
        event(freshness, CarSignalPolicy.Source.HEADSET, 2, 1_000);
        check(freshness.isFreshActive(61_000), "Presence remains fresh at sixty-second boundary");
        check(!freshness.isFreshActive(61_001), "Cached positive cannot hold forever after proxy loss");
        check(!freshness.isFreshActive(999), "Elapsed clock reversal refuses stale presence");
        check(!event(freshness, CarSignalPolicy.Source.HEADSET, 2, 62_000).changed, "Positive profile refresh does not duplicate edge");
        check(freshness.isFreshActive(63_000), "Positive public snapshot renews presence");
        check(freshness.getLastConfirmedActiveElapsedMillis() == 62_000, "Last authoritative positive is exposed");
        freshness.reset();
        check(freshness.getLastConfirmedActiveElapsedMillis() == -1 && !freshness.isFreshActive(63_001), "Reset clears presence proof");
        System.out.println("PASS " + checks + " host-only car signal policy checks; no Bluetooth or phone access.");
    }
}
