package org.json;

import java.util.*;

/** Small host-only JSON codec for synthetic state; never compiled into the APK. */
final class Json {
    static Object parse(String text) { Parser p = new Parser(text); Object value = p.value(); p.space(); if (p.i != text.length()) throw new IllegalArgumentException("Trailing JSON"); return value; }
    static String encode(Object value) {
        if (value == null || value == JSONObject.NULL) return "null";
        if (value instanceof String) {
            StringBuilder out = new StringBuilder("\"");
            for (char c : ((String)value).toCharArray()) {
                if (c == '"' || c == '\\') out.append('\\').append(c);
                else if (c < 32) out.append(String.format("\\u%04x", (int)c));
                else out.append(c);
            }
            return out.append('"').toString();
        }
        if (value instanceof Number || value instanceof Boolean) return value.toString();
        if (value instanceof JSONObject) {
            StringBuilder out = new StringBuilder("{"); boolean comma = false;
            JSONObject object = (JSONObject)value;
            for (String key : object.values.keySet()) { if (comma) out.append(','); comma = true; out.append(encode(key)).append(':').append(encode(object.values.get(key))); }
            return out.append('}').toString();
        }
        if (value instanceof JSONArray) {
            StringBuilder out = new StringBuilder("["); boolean comma = false;
            for (Object item : ((JSONArray)value).values) { if (comma) out.append(','); comma = true; out.append(encode(item)); }
            return out.append(']').toString();
        }
        throw new IllegalArgumentException("Unsupported JSON value");
    }
    private static final class Parser {
        final String text; int i;
        Parser(String text) { this.text = text; }
        void space() { while (i < text.length() && Character.isWhitespace(text.charAt(i))) i++; }
        char take() { if (i >= text.length()) throw new IllegalArgumentException("Truncated JSON"); return text.charAt(i++); }
        Object value() {
            space(); char c = take();
            if (c == '{') {
                JSONObject object = new JSONObject(); space(); if (text.charAt(i) == '}') { i++; return object; }
                do { space(); if (take() != '"') throw new IllegalArgumentException("Expected object key"); String key = string(); space(); if (take() != ':') throw new IllegalArgumentException("Expected colon"); object.put(key, value()); space(); c = take(); } while (c == ',');
                if (c != '}') throw new IllegalArgumentException("Expected object end"); return object;
            }
            if (c == '[') {
                JSONArray array = new JSONArray(); space(); if (text.charAt(i) == ']') { i++; return array; }
                do { array.put(value()); space(); c = take(); } while (c == ',');
                if (c != ']') throw new IllegalArgumentException("Expected array end"); return array;
            }
            if (c == '"') return string();
            i--; int start = i;
            while (i < text.length() && ",]} \t\r\n".indexOf(text.charAt(i)) < 0) i++;
            String token = text.substring(start, i);
            if (token.equals("true")) return Boolean.TRUE;
            if (token.equals("false")) return Boolean.FALSE;
            if (token.equals("null")) return JSONObject.NULL;
            if (token.matches("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")) {
                if (token.indexOf('.') >= 0 || token.indexOf('e') >= 0 || token.indexOf('E') >= 0) return Double.valueOf(token);
                return Long.valueOf(token);
            }
            throw new IllegalArgumentException("Invalid JSON token");
        }
        String string() {
            StringBuilder out = new StringBuilder();
            for (;;) {
                char c = take(); if (c == '"') return out.toString();
                if (c == '\\') {
                    c = take();
                    switch (c) {
                        case '"': case '\\': case '/': break;
                        case 'b': c = '\b'; break; case 'f': c = '\f'; break;
                        case 'n': c = '\n'; break; case 'r': c = '\r'; break; case 't': c = '\t'; break;
                        case 'u': if (i + 4 > text.length()) throw new IllegalArgumentException("Truncated escape"); c = (char)Integer.parseInt(text.substring(i, i + 4), 16); i += 4; break;
                        default: throw new IllegalArgumentException("Invalid JSON escape");
                    }
                } else if (c < 32) throw new IllegalArgumentException("Control in JSON string");
                out.append(c);
            }
        }
    }
}
