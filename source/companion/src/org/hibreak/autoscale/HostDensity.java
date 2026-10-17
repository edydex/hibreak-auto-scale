package org.hibreak.autoscale;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Parses the native virtual-display density requested by Android Auto's host.
 * No Android dependencies, device access, historical logs, or app-DPI inference.
 */
public final class HostDensity {
    private static final String AA = "com.google.android.projection.gearhead";
    private static final String ENTRY = "DisplayDeviceInfo{";
    private static final Pattern OWNER = Pattern.compile(
            "(?:^|,)\\s*owner\\s+([^\\s,(]+)\\s*\\(uid\\s+\\d+\\)");
    private static final Pattern DENSITY = Pattern.compile(
            "(?:^|,)\\s*density\\s+(-?\\d+)\\s*(?=,|$)");
    private static final Pattern STATE = Pattern.compile(
            "(?:^|,)\\s*state\\s+([A-Z_]+)\\s*(?=,|$)");
    private static final Pattern TYPE = Pattern.compile(
            "(?:^|,)\\s*type\\s+([A-Z_]+)\\s*(?=,|$)");

    private HostDensity() {}

    public static final class Surface {
        public final String name;
        public final int dpi;
        /** "host" for exact GhFacetBar/Dashboard names; "cluster" for conflict guards. */
        public final String kind;
        public final String state;

        private Surface(String name, int dpi, String kind, String state) {
            this.name = name;
            this.dpi = dpi;
            this.kind = kind;
            this.state = state;
        }
    }

    public static final class Result {
        /** An AA-owned, active GhFacetBar or Dashboard display exists. */
        public final boolean connected;
        /** Positive only when every authoritative display agrees and is valid. */
        public final int dpi;
        /** Null means the dump is certain; otherwise automatic writes must be refused. */
        public final String error;
        public final List<Surface> surfaces;
        /** Includes non-authoritative, inactive and app-drawn AA-owned displays. */
        public final boolean anyAaOwned;

        private Result(boolean connected, int dpi, String error,
                List<Surface> surfaces, boolean anyAaOwned) {
            this.connected = connected;
            this.dpi = dpi;
            this.error = error;
            this.surfaces = Collections.unmodifiableList(new ArrayList<Surface>(surfaces));
            this.anyAaOwned = anyAaOwned;
        }

        public boolean safeToApply() {
            return connected && error == null && dpi >= 72 && dpi <= 640;
        }
    }

    /**
     * A disconnected result is certain only if error is null and anyAaOwned is
     * false. Unknown AA surfaces can be negotiation or teardown, not disconnect.
     */
    public static Result parse(String dump) {
        List<Surface> surfaces = new ArrayList<Surface>();
        if (dump == null || dump.trim().isEmpty()) {
            return result(false, 0, "Display dump is empty", surfaces, false);
        }
        boolean anyAaOwned = false;
        boolean connected = false;
        int selected = 0;
        int entryCount = 0;
        int offset = 0;
        String failure = null;
        while (true) {
            int start = dump.indexOf(ENTRY, offset);
            if (start < 0) break;
            entryCount++;
            int bodyStart = start + ENTRY.length();
            int end = closingBrace(dump, bodyStart);
            if (end < 0) {
                // Uncertainty must never be interpreted as a clean disconnect.
                anyAaOwned |= dump.substring(start).contains(AA);
                failure = "Truncated or malformed DisplayDeviceInfo entry";
                break;
            }
            String body = dump.substring(bodyStart, end);
            offset = end + 1;
            String top = topLevel(body);
            Matcher ownerMatcher = OWNER.matcher(top);
            if (!ownerMatcher.find()) {
                if (body.contains(AA)) {
                    anyAaOwned = true;
                    failure = "Cannot establish owner of a potential Android Auto display";
                }
                continue;
            }
            if (!AA.equals(ownerMatcher.group(1))) continue;
            anyAaOwned = true;
            String name = quotedName(body);
            if (name == null) {
                failure = "Android Auto display has an unreadable name";
                continue;
            }
            String kind = kind(name);
            if (kind == null) continue;
            String state = singleValue(STATE, top);
            String type = singleValue(TYPE, top);
            String density = singleValue(DENSITY, top);
            int dpi = parseDensity(density);
            surfaces.add(new Surface(name, dpi, kind, state == null ? "UNKNOWN" : state));
            if (!"VIRTUAL".equals(type)) {
                failure = "Authoritative Android Auto display is not a verified virtual display";
            }
            if (state == null || "UNKNOWN".equals(state)) {
                failure = "Authoritative Android Auto display has an unknown state";
            }
            if (dpi < 72 || dpi > 640) {
                failure = "Authoritative Android Auto display density is missing or outside 72..640";
            }
            if ("host".equals(kind) && "ON".equals(state)) {
                connected = true;
                if (selected == 0) selected = dpi;
            }
        }
        if (entryCount == 0) {
            return result(false, 0, "No DisplayDeviceInfo entries in display dump", surfaces,
                    dump.contains(AA));
        }
        if (connected && selected >= 72 && selected <= 640) {
            for (Surface surface : surfaces) {
                // Even an inactive main/cluster can expose inconsistent host
                // negotiation; none may be hidden by a majority vote.
                if (surface.dpi != selected) {
                    failure = "Conflicting authoritative Android Auto display densities";
                    break;
                }
            }
        }
        if (failure != null) return result(connected, 0, failure, surfaces, anyAaOwned);
        if (!connected && anyAaOwned) {
            return result(false, 0,
                    "Android Auto displays exist without an active GhFacetBar or Dashboard host",
                    surfaces, true);
        }
        return result(connected, connected ? selected : 0, null, surfaces, anyAaOwned);
    }

    public static boolean hasAnyAaDisplay(String dump) {
        return parse(dump).anyAaOwned;
    }

    private static Result result(boolean connected, int dpi, String error,
            List<Surface> surfaces, boolean anyAaOwned) {
        return new Result(connected, dpi, error, surfaces, anyAaOwned);
    }

    private static String kind(String name) {
        if ("GhFacetBar".equals(name) || "Dashboard".equals(name)) return "host";
        String lower = name.toLowerCase(Locale.ROOT);
        if (lower.contains("ghostactivity") || lower.contains("carappservice")
                || lower.contains("template") || lower.contains("componentinfo")
                || lower.contains("/") || lower.contains("appdrawn")) return null;
        return lower.contains("cluster") ? "cluster" : null;
    }

    /** Finds the outer brace while respecting braces inside strings and structures. */
    private static int closingBrace(String input, int from) {
        int depth = 1;
        boolean quoted = false;
        boolean escaped = false;
        for (int i = from; i < input.length(); i++) {
            char c = input.charAt(i);
            if (quoted) {
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '"') quoted = false;
            } else if (c == '"') quoted = true;
            else if (c == '{') depth++;
            else if (c == '}' && --depth == 0) return i;
        }
        return -1;
    }

    /** Masks quoted/nested data so display names cannot spoof owner/density fields. */
    private static String topLevel(String body) {
        StringBuilder result = new StringBuilder(body.length());
        int nested = 0;
        boolean quoted = false;
        boolean escaped = false;
        for (int i = 0; i < body.length(); i++) {
            char c = body.charAt(i);
            if (quoted) {
                result.append(' ');
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '"') quoted = false;
            } else if (c == '"') {
                quoted = true;
                result.append(' ');
            } else if (c == '{' || c == '[') {
                nested++;
                result.append(' ');
            } else if (c == '}' || c == ']') {
                nested--;
                result.append(' ');
            } else result.append(nested == 0 ? c : ' ');
        }
        return result.toString();
    }

    private static String quotedName(String body) {
        int index = 0;
        while (index < body.length() && Character.isWhitespace(body.charAt(index))) index++;
        if (index >= body.length() || body.charAt(index++) != '"') return null;
        StringBuilder name = new StringBuilder();
        boolean escaped = false;
        for (; index < body.length(); index++) {
            char c = body.charAt(index);
            if (escaped) {
                name.append(c);
                escaped = false;
            } else if (c == '\\') escaped = true;
            else if (c == '"') {
                int after = index + 1;
                while (after < body.length() && Character.isWhitespace(body.charAt(after))) after++;
                return after < body.length() && body.charAt(after) == ':' ? name.toString() : null;
            } else name.append(c);
        }
        return null;
    }

    private static String singleValue(Pattern pattern, String input) {
        Matcher matcher = pattern.matcher(input);
        if (!matcher.find()) return null;
        String value = matcher.group(1);
        return matcher.find() ? null : value;
    }

    private static int parseDensity(String value) {
        try {
            return value == null ? 0 : Integer.parseInt(value);
        } catch (NumberFormatException invalid) {
            return 0;
        }
    }
}
