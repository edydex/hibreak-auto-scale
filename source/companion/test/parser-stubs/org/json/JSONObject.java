package org.json;
import java.util.LinkedHashMap;
import java.util.Map;
/** Host-only typed object stand-in for production logic checks, not a JSON parser. */
public final class JSONObject {
    public static final Object NULL = new Object();
    private final Map<String,Object> values = new LinkedHashMap<String,Object>();
    public JSONObject put(String key, Object value) { values.put(key, value); return this; }
    public JSONObject put(String key, boolean value) { values.put(key, value); return this; }
    public JSONObject put(String key, long value) { values.put(key, value); return this; }
    public JSONObject put(String key, double value) { values.put(key, value); return this; }
    public Object get(String key) { if (!values.containsKey(key)) throw new IllegalStateException("Missing key: " + key); return values.get(key); }
    public boolean has(String key) { return values.containsKey(key); }
    public int length() { return values.size(); }
    public String getString(String key) { return String.valueOf(get(key)); }
    public String optString(String key) { Object value = values.get(key); return value == null ? "" : String.valueOf(value); }
    public boolean optBoolean(String key) { return Boolean.TRUE.equals(values.get(key)); }
    @Override public String toString() { return values.toString(); }
}
