package org.json;

import java.util.ArrayList;
import java.util.List;

/** Minimal host-only JSON stand-in; never included in the Android DEX. */
public final class JSONArray {
    private final List<Object> values = new ArrayList<Object>();
    public JSONArray put(Object value) { values.add(value); return this; }
    public int length() { return values.size(); }
    @Override public String toString() { return values.toString(); }
}
