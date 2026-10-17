import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import org.json.JSONObject;
import xrz.framework.manager.DisplayPolicy;

/** Checks mutation evidence and failure paths without Android or a device. */
public final class BridgeWriteTest {
    public interface PolicyInterface {
        DisplayPolicy getPolicyByPackage(String packageName);
        boolean setDpiForPackage(String packageName, int value) throws Exception;
        boolean setIsDpiSettingForPackage(String packageName, int value) throws Exception;
        boolean setTextEnhanceForPackage(String packageName, int value) throws Exception;
    }

    public static final class FakeService implements PolicyInterface {
        DisplayPolicy policy = new DisplayPolicy();
        boolean accepted = true;
        boolean update = true;
        int setters = 0;
        public DisplayPolicy getPolicyByPackage(String name) { return policy; }
        private boolean set(String field, int value) throws Exception {
            setters++;
            if (update) policy.set(field, value);
            return accepted;
        }
        public boolean setDpiForPackage(String name, int value) throws Exception { return set("appDpi", value); }
        public boolean setIsDpiSettingForPackage(String name, int value) throws Exception { return set("isDpiSetting", value); }
        public boolean setTextEnhanceForPackage(String name, int value) throws Exception { return set("appTextEnhance", value); }
    }

    public interface WrongSetterSignature {
        DisplayPolicy getPolicyByPackage(String name);
        int setDpiForPackage(String name, int value);
    }

    public interface WrongGetterSignature {
        Object getPolicyByPackage(String name);
        boolean setDpiForPackage(String name, int value);
    }

    private static Method writer;

    public static void main(String[] args) throws Exception {
        writer = Class.forName("DisplayPolicyBridge").getDeclaredMethod("applyVerifiedSetting",
                JSONObject.class, Class.class, Object.class, String.class, String.class, Integer.TYPE);
        writer.setAccessible(true);
        checkSuccessfulWrite("set-dpi", 0, "appDpi", 32);
        checkSuccessfulWrite("set-dpi-enabled", 1, "isDpiSetting", 0);
        checkSuccessfulWrite("set-text-enhance", 0, "appTextEnhance", 4);

        FakeService rejected = new FakeService();
        rejected.accepted = false; // Include the case where false still changed state.
        JSONObject rejectedResult = invoke(PolicyInterface.class, rejected, "set-dpi", 100, true);
        check(Boolean.FALSE.equals(rejectedResult.get("setterResult")), "false setter result retained");
        check(readField(rejectedResult, "afterPolicy", "appDpi").equals(100), "false result still captures actual changed policy");
        check(Boolean.FALSE.equals(verification(rejectedResult).get("verified")), "false setter never verifies");

        FakeService ignored = new FakeService();
        ignored.update = false;
        JSONObject ignoredResult = invoke(PolicyInterface.class, ignored, "set-dpi", 100, true);
        check(Boolean.TRUE.equals(ignoredResult.get("setterResult")), "accepted mismatch retains setter result");
        check(Boolean.FALSE.equals(verification(ignoredResult).get("matchesRequested")), "readback mismatch detected");
        check(readField(ignoredResult, "beforePolicy", "appDpi").equals(32), "before evidence retained on mismatch");

        FakeService absent = new FakeService();
        absent.policy = null;
        JSONObject absentResult = invoke(PolicyInterface.class, absent, "set-dpi", 100, true);
        check(absent.setters == 0 && Boolean.FALSE.equals(absentResult.get("mutationAttempted")), "null pre-policy prevents write");

        FakeService untouched = new FakeService();
        JSONObject wrongSetter = invoke(WrongSetterSignature.class, untouched, "set-dpi", 100, true);
        JSONObject wrongGetter = invoke(WrongGetterSignature.class, untouched, "set-dpi", 100, true);
        check(untouched.setters == 0 && Boolean.FALSE.equals(wrongSetter.get("mutationAttempted"))
                && Boolean.FALSE.equals(wrongGetter.get("mutationAttempted")), "signature drift prevents write");
        System.out.println("PASS: 3 successful writes and 5 failure/evidence scenarios; host fakes only, no device accessed.");
    }

    private static void checkSuccessfulWrite(String command, int requested, String field, int oldValue) throws Exception {
        FakeService fake = new FakeService();
        JSONObject result = invoke(PolicyInterface.class, fake, command, requested, false);
        check(fake.setters == 1, "exactly one setter invoked");
        check(readField(result, "beforePolicy", field).equals(oldValue), "before snapshot survives shared mutable fake");
        check(readField(result, "afterPolicy", field).equals(requested), "after requested value");
        check(Boolean.TRUE.equals(verification(result).get("verified")), "successful verification");
    }

    private static JSONObject invoke(Class<?> iface, Object proxy, String command, int value, boolean expectFailure) throws Exception {
        JSONObject result = new JSONObject().put("mutationAttempted", false);
        try {
            writer.invoke(null, result, iface, proxy, command, "com.example.app", value);
            check(!expectFailure, "expected operation failure");
        } catch (InvocationTargetException error) {
            if (!expectFailure) throw error;
            check(error.getTargetException() instanceof IllegalStateException, "expected explicit validation failure");
        }
        return result;
    }

    private static JSONObject verification(JSONObject result) { return (JSONObject) result.get("verification"); }
    private static Object readField(JSONObject result, String policy, String field) {
        return ((JSONObject) ((JSONObject) result.get(policy)).get("fields")).get(field);
    }
    private static void check(boolean okay, String description) {
        if (!okay) throw new AssertionError(description);
    }
}
