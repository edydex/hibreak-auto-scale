package org.json;
import java.util.*;
/** Host-only typed JSON stand-in, with a real codec for production deep copies. */
public final class JSONObject {
    public static final Object NULL = new Object();
    final Map<String,Object> values = new LinkedHashMap<String,Object>();
    public JSONObject() {}
    public JSONObject(String text) { Object value = Json.parse(text); if (!(value instanceof JSONObject)) throw new IllegalArgumentException("Expected object"); values.putAll(((JSONObject)value).values); }
    public JSONObject put(String key, Object value) { values.put(key, value == null ? NULL : value); return this; }
    public Object get(String key) { if (!values.containsKey(key)) throw new IllegalStateException("Missing key: " + key); return values.get(key); }
    public Object opt(String key) { return values.get(key); }
    public boolean has(String key) { return values.containsKey(key); }
    public Object remove(String key) { return values.remove(key); }
    public int length() { return values.size(); }
    public Iterator<String> keys() { return values.keySet().iterator(); }
    public JSONObject getJSONObject(String key) { return (JSONObject)get(key); }
    public JSONObject optJSONObject(String key) { Object v = opt(key); return v instanceof JSONObject ? (JSONObject)v : null; }
    public JSONArray getJSONArray(String key) { return (JSONArray)get(key); }
    public JSONArray optJSONArray(String key) { Object v = opt(key); return v instanceof JSONArray ? (JSONArray)v : null; }
    public String getString(String key) { return String.valueOf(get(key)); }
    public String optString(String key) { return optString(key, ""); }
    public String optString(String key, String fallback) { Object v = opt(key); return v == null || v == NULL ? fallback : String.valueOf(v); }
    public boolean getBoolean(String key) { return (Boolean)get(key); }
    public boolean optBoolean(String key) { return Boolean.TRUE.equals(opt(key)); }
    public int getInt(String key) { return ((Number)get(key)).intValue(); }
    public int optInt(String key) { return optInt(key, 0); }
    public int optInt(String key, int fallback) { Object v = opt(key); return v instanceof Number ? ((Number)v).intValue() : fallback; }
    public long getLong(String key) { return ((Number)get(key)).longValue(); }
    public long optLong(String key, long fallback) { Object v = opt(key); return v instanceof Number ? ((Number)v).longValue() : fallback; }
    public double getDouble(String key) { return ((Number)get(key)).doubleValue(); }
    public JSONArray names() { if (values.isEmpty()) return null; JSONArray result = new JSONArray(); for (String key : values.keySet()) result.put(key); return result; }
    @Override public String toString() { return Json.encode(this); }
}
