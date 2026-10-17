package org.json;

import java.util.LinkedHashMap;
import java.util.Map;

/** Minimal host-only JSON stand-in; never included in the Android DEX. */
public final class JSONObject {
    public static final Object NULL = new Object();
    private final Map<String, Object> values = new LinkedHashMap<String, Object>();
    public JSONObject put(String key, Object value) { values.put(key, value); return this; }
    public Object get(String key) { return values.get(key); }
    public int length() { return values.size(); }
    public java.util.Iterator<String> keys() { return values.keySet().iterator(); }
    @Override public String toString() { return values.toString(); }
}
