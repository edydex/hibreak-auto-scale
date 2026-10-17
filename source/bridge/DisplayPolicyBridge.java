import android.os.Build;
import android.os.IBinder;
import android.os.Process;
import org.json.JSONArray;
import org.json.JSONObject;

import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.IdentityHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.Iterator;

/**
 * app_process/shell diagnostics and three explicit per-package display-policy
 * setters. There are no raw transact or arbitrary-invocation commands.
 */
public final class DisplayPolicyBridge {
    private static final String SERVICE = "xrz_display_policy_service";
    private static final String INTERFACE = "xrz.framework.manager.IDisplayPolicyManager";
    private static final String[] SAFE_PACKAGE_GETTERS = {
        "getPolicyByPackage", "getDisplayPolicyForPackage", "getPackageDisplayPolicy",
        "getDisplayPolicyByPackage", "getDisplayPolicy", "getPackagePolicy"
    };
    private static final int MAX_DEPTH = 5;
    private static final int MAX_ITEMS = 64;
    private static IBinder cachedBinder;
    private static IBinder proxyBinder;
    private static Object cachedProxy;

    private DisplayPolicyBridge() {}

    public static void main(String[] args) {
        if (args.length == 1 && "serve".equals(args[0])) { serve(); return; }
        JSONObject result = request(args);
        System.out.println(result.toString());
        if (!result.optBoolean("ok", false)) System.exit(1);
    }

    private static void serve() {
        PrintWriter output = new PrintWriter(System.out, true);
        JSONObject ready = new JSONObject();
        put(ready, "bridgeVersion", 3); put(ready, "ready", true); put(ready, "uid", Process.myUid()); put(ready, "readOnly", true);
        output.println(ready.toString());
        try (BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = input.readLine()) != null) {
                JSONObject result;
                try {
                    if (line.length() > 8192) throw new IllegalArgumentException("Protocol request exceeds limit");
                    result = request(requestArguments(new JSONObject(line)));
                } catch (Throwable error) {
                    result = new JSONObject(); put(result, "bridgeVersion", 3); put(result, "uid", Process.myUid());
                    put(result, "ok", false); put(result, "readOnly", true); put(result, "error", describeError(error));
                }
                output.println(result.toString());
                if (output.checkError()) return;
            }
        } catch (Throwable ignored) { /* EOF/broken client ends this same-UID helper. */ }
    }

    private static String[] requestArguments(JSONObject input) throws Exception {
        Iterator<String> keys = input.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            if (!"command".equals(key) && !"package".equals(key) && !"value".equals(key)) throw new IllegalArgumentException("Unknown protocol field: " + key);
        }
        Object rawCommand = input.get("command");
        if (!(rawCommand instanceof String)) throw new IllegalArgumentException("command must be a string");
        String command = (String)rawCommand;
        if ("inspect".equals(command)) {
            if (input.length() != 1) throw new IllegalArgumentException("inspect accepts no package/value");
            return new String[]{command};
        }
        if (!"get".equals(command) && !"set-dpi".equals(command) && !"set-dpi-enabled".equals(command) && !"set-text-enhance".equals(command)) {
            throw new IllegalArgumentException("Command outside protocol allowlist");
        }
        Object pkg = input.get("package");
        if (!(pkg instanceof String)) throw new IllegalArgumentException("package must be a string");
        if ("get".equals(command)) {
            if (input.length() != 2) throw new IllegalArgumentException("get accepts only package");
            return new String[]{command, (String)pkg};
        }
        if (input.length() != 3) throw new IllegalArgumentException("setter requires package/value");
        Object value = input.get("value");
        if (!(value instanceof Integer) && !(value instanceof Long)) throw new IllegalArgumentException("value must be an integer");
        long integer = ((Number)value).longValue();
        if (integer < Integer.MIN_VALUE || integer > Integer.MAX_VALUE) throw new IllegalArgumentException("value exceeds integer bounds");
        return new String[]{command, (String)pkg, String.valueOf(integer)};
    }

    private static JSONObject request(String[] args) {
        JSONObject result = new JSONObject();
        try {
            put(result, "bridgeVersion", 3);
            put(result, "buildFingerprint", Build.FINGERPRINT);
            put(result, "sdkInt", Build.VERSION.SDK_INT);
            put(result, "uid", Process.myUid());
            put(result, "serviceName", SERVICE);
            put(result, "interfaceName", INTERFACE);
            String command = args.length == 0 ? "inspect" : args[0];
            boolean inspect = "inspect".equals(command);
            put(result, "command", command);
            boolean write = "set-dpi".equals(command) || "set-dpi-enabled".equals(command)
                    || "set-text-enhance".equals(command);
            put(result, "readOnly", !write);
            if (!("inspect".equals(command) && args.length <= 1)
                    && !("get".equals(command) && args.length == 2)
                    && !(write && args.length == 3)) {
                throw new IllegalArgumentException("Usage: DisplayPolicyBridge [inspect | get PACKAGE | set-dpi PACKAGE 0..1000 | set-dpi-enabled PACKAGE 0|1 | set-text-enhance PACKAGE 0..100]");
            }
            if (("get".equals(command) || write) && !args[1].matches("[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)+")) {
                throw new IllegalArgumentException("PACKAGE must be an Android package name");
            }
            int requestedValue = 0;
            if (write) {
                requestedValue = Integer.parseInt(args[2]);
                int maximum = "set-dpi".equals(command) ? 1000 : "set-dpi-enabled".equals(command) ? 1 : 100;
                if (requestedValue < 0 || requestedValue > maximum) {
                    throw new IllegalArgumentException(command + " requires an integer in 0.." + maximum);
                }
                put(result, "package", args[1]);
                put(result, "requestedValue", requestedValue);
                put(result, "mutationAttempted", false);
            }

            Class<?> iface = null;
            Class<?> stub = null;
            try {
                iface = Class.forName(INTERFACE);
                if (inspect) put(result, "interface", describeClass(iface, false));
            } catch (Throwable error) {
                put(result, "interfaceLoadError", describeError(error));
            }
            try {
                stub = Class.forName(INTERFACE + "$Stub");
                if (inspect) put(result, "stub", describeClass(stub, true));
            } catch (Throwable error) {
                put(result, "stubLoadError", describeError(error));
            }

            IBinder binder = findBinder();
            JSONObject binderInfo = new JSONObject();
            put(result, "binder", binderInfo);
            put(binderInfo, "found", binder != null);
            if (binder == null) throw new IllegalStateException("The display-policy service is not registered");
            put(binderInfo, "class", binder.getClass().getName());
            put(binderInfo, "alive", binder.isBinderAlive());
            put(binderInfo, "ping", binder.pingBinder());
            put(binderInfo, "descriptor", binder.getInterfaceDescriptor());
            if (inspect) put(binderInfo, "declaredMethods", describeMethods(binder.getClass()));
            if (iface == null || stub == null) {
                throw new IllegalStateException("Vendor interface classes are unavailable on the process class path; no raw Binder transactions are attempted");
            }
            Object proxy;
            if (proxyBinder == binder && cachedProxy != null) proxy = cachedProxy;
            else {
                Method asInterface = stub.getDeclaredMethod("asInterface", IBinder.class);
                asInterface.setAccessible(true);
                proxy = asInterface.invoke(null, binder);
                proxyBinder = binder; cachedProxy = proxy;
            }
            if (proxy == null) throw new IllegalStateException("Stub.asInterface returned null");
            put(result, "proxyClass", proxy.getClass().getName());
            if (inspect) put(result, "proxyMethods", describeMethods(proxy.getClass()));

            JSONArray candidates = new JSONArray();
            List<Method> getters = safeGetters(iface);
            if (inspect) for (Method method : getters) {
                JSONObject getter = describeMethod(method);
                put(getter, "returnSchema", describeFields(method.getReturnType(), 0, new LinkedHashSet<String>()));
                candidates.put(getter);
            }
            if (inspect) put(result, "allowlistedPackageGetters", candidates);
            if ("get".equals(command)) {
                if (getters.isEmpty()) {
                    throw new IllegalStateException("No allowlisted single-String package-policy getter was discovered; inspect the interface before adding a verified getter");
                }
                Method method = getters.get(0);
                put(result, "package", args[1]);
                put(result, "getter", describeMethod(method));
                Object value = method.invoke(proxy, args[1]);
                put(result, "value", serialize(value, 0, new IdentityHashMap<Object, Boolean>()));
            }
            if (write) applyVerifiedSetting(result, iface, proxy, command, args[1], requestedValue);
            put(result, "ok", true);
        } catch (Throwable error) {
            put(result, "ok", false);
            put(result, "error", describeError(error));
        }
        return result;
    }

    private static void applyVerifiedSetting(JSONObject result, Class<?> iface, Object proxy,
            String command, String packageName, int requestedValue) throws Exception {
        final String setterName;
        final String fieldName;
        if ("set-dpi".equals(command)) {
            setterName = "setDpiForPackage";
            fieldName = "appDpi";
        } else if ("set-dpi-enabled".equals(command)) {
            setterName = "setIsDpiSettingForPackage";
            fieldName = "isDpiSetting";
        } else if ("set-text-enhance".equals(command)) {
            setterName = "setTextEnhanceForPackage";
            fieldName = "appTextEnhance";
        } else {
            throw new IllegalArgumentException("Unrecognized write command");
        }

        // All signatures and readback field access are validated before a write.
        Method getter = iface.getMethod("getPolicyByPackage", String.class);
        if (Modifier.isStatic(getter.getModifiers())
                || !"xrz.framework.manager.DisplayPolicy".equals(getter.getReturnType().getName())) {
            throw new IllegalStateException("Unexpected getPolicyByPackage signature: " + getter.toGenericString());
        }
        Method setter = iface.getMethod(setterName, String.class, Integer.TYPE);
        if (Modifier.isStatic(setter.getModifiers()) || setter.getReturnType() != Boolean.TYPE) {
            throw new IllegalStateException("Unexpected setter signature: " + setter.toGenericString());
        }
        put(result, "getter", describeMethod(getter));
        put(result, "setter", describeMethod(setter));

        Object before = getter.invoke(proxy, packageName);
        Field beforeField = findIntField(before, fieldName);
        int beforeValue = beforeField.getInt(before);
        put(result, "beforePolicy", serialize(before, 0, new IdentityHashMap<Object, Boolean>()));
        JSONObject verification = new JSONObject();
        put(result, "verification", verification);
        put(verification, "field", fieldName);
        put(verification, "fieldDeclaringClass", beforeField.getDeclaringClass().getName());
        put(verification, "fieldType", beforeField.getType().getName());
        put(verification, "beforeValue", beforeValue);
        put(verification, "requestedValue", requestedValue);
        put(verification, "verified", false);

        put(result, "mutationAttempted", true);
        boolean accepted = (Boolean) setter.invoke(proxy, packageName, requestedValue);
        put(result, "setterResult", accepted);
        Object after = getter.invoke(proxy, packageName);
        Field afterField = findIntField(after, fieldName);
        int actualValue = afterField.getInt(after);
        put(result, "afterPolicy", serialize(after, 0, new IdentityHashMap<Object, Boolean>()));
        put(verification, "afterValue", actualValue);
        put(verification, "setterAccepted", accepted);
        put(verification, "matchesRequested", actualValue == requestedValue);
        put(verification, "verified", accepted && actualValue == requestedValue);
        if (!accepted) throw new IllegalStateException("Vendor setter returned false; after-policy was captured; no automatic rollback was attempted");
        if (actualValue != requestedValue) {
            throw new IllegalStateException("Policy readback mismatch for " + fieldName + ": requested " + requestedValue + ", read " + actualValue + "; no automatic rollback was attempted");
        }
    }

    private static Field findIntField(Object policy, String name) throws Exception {
        if (policy == null) throw new IllegalStateException("Policy getter returned null");
        for (Class<?> type = policy.getClass(); type != null && type != Object.class; type = type.getSuperclass()) {
            try {
                Field field = type.getDeclaredField(name);
                if (Modifier.isStatic(field.getModifiers()) || field.getType() != Integer.TYPE) {
                    throw new IllegalStateException("Expected an instance int field for " + name);
                }
                field.setAccessible(true);
                return field;
            } catch (NoSuchFieldException missing) {
                // Continue through the actual runtime policy hierarchy.
            }
        }
        throw new NoSuchFieldException("Policy does not expose expected readback field " + name);
    }

    private static IBinder findBinder() throws Exception {
        if (cachedBinder != null && cachedBinder.isBinderAlive()) return cachedBinder;
        Class<?> serviceManager = Class.forName("android.os.ServiceManager");
        Method checkService = serviceManager.getDeclaredMethod("checkService", String.class);
        checkService.setAccessible(true);
        cachedBinder = (IBinder) checkService.invoke(null, SERVICE);
        return cachedBinder;
    }

    private static List<Method> safeGetters(Class<?> iface) {
        List<Method> result = new ArrayList<Method>();
        // Keep the deliberate allowlist order; do not select an arbitrary method by its prefix.
        for (String name : SAFE_PACKAGE_GETTERS) {
            for (Method method : iface.getMethods()) {
                if (method.getName().equals(name)
                        && !Modifier.isStatic(method.getModifiers())
                        && method.getReturnType() != Void.TYPE
                        && Arrays.equals(method.getParameterTypes(), new Class<?>[]{String.class})) {
                    result.add(method);
                }
            }
        }
        return result;
    }

    private static JSONObject describeClass(Class<?> type, boolean constants) throws Exception {
        JSONObject result = new JSONObject();
        put(result, "name", type.getName());
        put(result, "declaredMethods", describeMethods(type));
        put(result, "declaredFields", describeFields(type, 0, new LinkedHashSet<String>()));
        if (constants) {
            JSONObject values = new JSONObject();
            for (Field field : sortedFields(type)) {
                if (Modifier.isStatic(field.getModifiers())
                        && (field.getName().startsWith("TRANSACTION_") || field.getName().equals("DESCRIPTOR"))) {
                    try {
                        field.setAccessible(true);
                        put(values, field.getName(), serialize(field.get(null), 0, new IdentityHashMap<Object, Boolean>()));
                    } catch (Throwable error) {
                        put(values, field.getName(), describeError(error));
                    }
                }
            }
            put(result, "transactionConstantsAndDescriptor", values);
        }
        return result;
    }

    private static JSONArray describeMethods(Class<?> type) throws Exception {
        Method[] methods = type.getDeclaredMethods();
        Arrays.sort(methods, Comparator.comparing(Method::toGenericString));
        JSONArray result = new JSONArray();
        for (Method method : methods) result.put(describeMethod(method));
        return result;
    }

    private static JSONObject describeMethod(Method method) throws Exception {
        JSONObject result = new JSONObject();
        put(result, "declaringClass", method.getDeclaringClass().getName());
        put(result, "name", method.getName());
        put(result, "signature", method.toGenericString());
        put(result, "modifiers", Modifier.toString(method.getModifiers()));
        put(result, "returnType", method.getReturnType().getName());
        JSONArray parameters = new JSONArray();
        for (Class<?> parameter : method.getParameterTypes()) parameters.put(parameter.getName());
        put(result, "parameterTypes", parameters);
        JSONArray exceptions = new JSONArray();
        for (Class<?> exception : method.getExceptionTypes()) exceptions.put(exception.getName());
        put(result, "exceptionTypes", exceptions);
        return result;
    }

    private static JSONObject describeFields(Class<?> type, int depth, Set<String> seen) throws Exception {
        JSONObject result = new JSONObject();
        put(result, "class", type.getName());
        if (type.isArray()) {
            put(result, "component", describeFields(type.getComponentType(), depth + 1, seen));
            return result;
        }
        if (isScalar(type) || depth >= 3 || !seen.add(type.getName())) return result;
        JSONArray fields = new JSONArray();
        put(result, "fields", fields);
        for (Field field : sortedFields(type)) {
            JSONObject item = new JSONObject();
            put(item, "name", field.getName());
            put(item, "type", field.getType().getName());
            put(item, "modifiers", Modifier.toString(field.getModifiers()));
            if (!Modifier.isStatic(field.getModifiers()) && !isScalar(field.getType())) {
                put(item, "schema", describeFields(field.getType(), depth + 1, seen));
            }
            fields.put(item);
            if (fields.length() >= MAX_ITEMS) { put(result, "truncated", true); break; }
        }
        Class<?> parent = type.getSuperclass();
        if (parent != null && parent != Object.class) put(result, "superclass", describeFields(parent, depth + 1, seen));
        return result;
    }

    private static Field[] sortedFields(Class<?> type) {
        Field[] fields = type.getDeclaredFields();
        Arrays.sort(fields, Comparator.comparing(Field::getName));
        return fields;
    }

    private static boolean isScalar(Class<?> type) {
        return type.isPrimitive() || type == String.class || type == Boolean.class
                || type == Character.class || Number.class.isAssignableFrom(type) || type.isEnum();
    }

    private static Object serialize(Object value, int depth, IdentityHashMap<Object, Boolean> seen) throws Exception {
        if (value == null) return JSONObject.NULL;
        Class<?> type = value.getClass();
        if (value instanceof String || value instanceof Boolean || value instanceof Number) return value;
        if (value instanceof Character) return String.valueOf(value);
        if (value instanceof Enum<?>) return ((Enum<?>) value).name();
        JSONObject result = new JSONObject();
        put(result, "class", type.getName());
        if (depth >= MAX_DEPTH) { put(result, "depthLimit", true); return result; }
        if (seen.put(value, Boolean.TRUE) != null) { put(result, "repeatedReference", true); return result; }
        if (type.isArray()) {
            int length = Array.getLength(value);
            JSONArray items = new JSONArray();
            for (int i = 0; i < Math.min(length, MAX_ITEMS); i++) items.put(serialize(Array.get(value, i), depth + 1, seen));
            put(result, "length", length);
            put(result, "items", items);
            if (length > MAX_ITEMS) put(result, "truncated", true);
            return result;
        }
        // Do not invoke toString(), accessors, or arbitrary collection methods on vendor objects.
        JSONObject fields = new JSONObject();
        put(result, "fields", fields);
        int count = 0;
        for (Class<?> current = type; current != null && current != Object.class; current = current.getSuperclass()) {
            for (Field field : sortedFields(current)) {
                if (Modifier.isStatic(field.getModifiers()) || field.isSynthetic()) continue;
                if (++count > MAX_ITEMS) { put(result, "truncated", true); return result; }
                String key = current == type ? field.getName() : current.getName() + "#" + field.getName();
                try {
                    field.setAccessible(true);
                    put(fields, key, serialize(field.get(value), depth + 1, seen));
                } catch (Throwable error) {
                    put(fields, key, describeError(error));
                }
            }
        }
        return result;
    }

    private static JSONObject describeError(Throwable throwable) {
        Throwable error = throwable;
        while (error instanceof InvocationTargetException && ((InvocationTargetException) error).getTargetException() != null) {
            error = ((InvocationTargetException) error).getTargetException();
        }
        JSONObject result = new JSONObject();
        put(result, "class", error.getClass().getName());
        put(result, "message", error.getMessage() == null ? JSONObject.NULL : error.getMessage());
        StackTraceElement[] stack = error.getStackTrace();
        JSONArray frames = new JSONArray();
        for (int i = 0; i < Math.min(stack.length, 8); i++) frames.put(stack[i].toString());
        put(result, "stack", frames);
        return result;
    }

    private static void put(JSONObject object, String key, Object value) {
        try { object.put(key, value == null ? JSONObject.NULL : value); }
        catch (Exception error) { throw new IllegalStateException("JSON encoding failed for " + key, error); }
    }
}
