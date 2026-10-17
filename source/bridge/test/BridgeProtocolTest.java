import java.lang.reflect.*;
import java.util.Arrays;
import org.json.JSONObject;

/** Validates the server's bounded command schema without invoking Android. */
public final class BridgeProtocolTest {
    private static Method parser;
    private static int checks;
    public static void main(String[] args) throws Exception {
        parser = Class.forName("DisplayPolicyBridge").getDeclaredMethod("requestArguments", JSONObject.class);
        parser.setAccessible(true);
        accept(new JSONObject().put("command", "inspect"), new String[]{"inspect"});
        accept(new JSONObject().put("command", "get").put("package", "com.example.app"), new String[]{"get", "com.example.app"});
        for (String command : new String[]{"set-dpi", "set-dpi-enabled", "set-text-enhance"}) {
            accept(new JSONObject().put("command", command).put("package", "com.example.app").put("value", 1), new String[]{command, "com.example.app", "1"});
        }
        reject(new JSONObject().put("command", "serve"));
        reject(new JSONObject().put("command", "invoke").put("package", "com.example.app").put("value", 1));
        reject(new JSONObject().put("command", "inspect").put("package", "com.example.app"));
        reject(new JSONObject().put("command", "get").put("package", "com.example.app").put("value", 1));
        reject(new JSONObject().put("command", "get").put("package", "com.example.app").put("method", "arbitrary"));
        reject(new JSONObject().put("command", "get"));
        reject(new JSONObject().put("command", 12));
        reject(new JSONObject().put("command", "set-dpi").put("package", "com.example.app").put("value", "160"));
        reject(new JSONObject().put("command", "set-dpi").put("package", "com.example.app").put("value", 160.0));
        reject(new JSONObject().put("command", "set-dpi").put("package", "com.example.app").put("value", Long.MAX_VALUE));
        System.out.println("PASS: " + checks + " host-only fixed-protocol boundary checks; no device accessed.");
    }
    private static void accept(JSONObject request, String[] expected) throws Exception {
        String[] actual = (String[])parser.invoke(null, request);
        if (!Arrays.equals(actual, expected)) throw new AssertionError("Protocol arguments differ");
        checks++;
    }
    private static void reject(JSONObject request) throws Exception {
        try { parser.invoke(null, request); throw new AssertionError("Invalid protocol accepted"); }
        catch (InvocationTargetException expected) {
            if (!(expected.getTargetException() instanceof IllegalArgumentException)) throw expected;
        }
        checks++;
    }
}
