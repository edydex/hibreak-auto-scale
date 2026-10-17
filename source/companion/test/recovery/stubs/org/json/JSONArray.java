package org.json;
import java.util.*;
/** Host-only JSON array; never compiled into the APK. */
public final class JSONArray {
    final List<Object> values = new ArrayList<Object>();
    public JSONArray put(Object value) { values.add(value == null ? JSONObject.NULL : value); return this; }
    public Object get(int index) { return values.get(index); }
    public int length() { return values.size(); }
    @Override public String toString() { return Json.encode(this); }
}
