package org.hibreak.autoscale;

import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.regex.*;
import org.json.JSONObject;

/** Executes the production parser with host stand-ins for Android clock/log/JSON objects. */
public final class PolicyRowsTest {
    private static Method parse;
    private static int checks;
    public static void main(String[] args) throws Exception {
        Class<?> engine = Class.forName("org.hibreak.autoscale.ScaleEngine");
        parse = engine.getDeclaredMethod("parseRows", String.class); parse.setAccessible(true);
        Pattern integer = pattern(engine, "INTEGER_VALUE_PATTERN"), decimal = pattern(engine, "DECIMAL_VALUE_PATTERN");
        String[] tokens = {"0", "-0", "160", "-160", "0001", "1.0", "-1.25", "00.00", "+1", ".1", "1.", "1e2", "NaN", "", " 1", "1 ", "--1", "1,2", "1\n"};
        Matcher integerMatcher = integer.matcher(""), decimalMatcher = decimal.matcher("");
        for (String token : tokens) {
            check(integerMatcher.reset(token).matches() == token.matches("-?\\d+"), "legacy integer equivalence: " + token);
            check(decimalMatcher.reset(token).matches() == token.matches("-?\\d+\\.\\d+"), "legacy decimal equivalence: " + token);
        }
        JSONObject rows = parse("Top app:\n com.example\nPolicy list:\n DisplayPolicy{packageName='com.example', appDpi=00160, signed=-2, appDpiScale=1.0, decimal=-1.25}\n");
        JSONObject row = (JSONObject)rows.get("com.example");
        check(rows.length() == 1, "one row");
        check(row.get("appDpi") instanceof Long && row.get("appDpi").equals(160L), "integer type/value unchanged");
        check(row.get("signed").equals(-2L), "negative integer");
        check(row.get("appDpiScale") instanceof Double && row.get("appDpiScale").equals(1.0), "decimal type/value unchanged");
        check(row.get("decimal").equals(-1.25), "negative decimal");
        reject("No header\nDisplayPolicy{packageName='p', appDpi=160}", "readable rows");
        reject("Permission Denial\nPolicy list:\nDisplayPolicy{packageName='p', appDpi=160}", "readable rows");
        reject("Policy list:\n", "empty");
        reject("Policy list:\nDisplayPolicy{packageName='p', appDpi=160, appDpi=240}", "Duplicate policy row field");
        reject("Policy list:\nDisplayPolicy{packageName='p', appDpi=160}\nDisplayPolicy{packageName='p', appDpi=240}", "Duplicate policy row package");
        reject("Policy list:\nDisplayPolicy{packageName='p', garbage}", "Unknown policy row format");
        for (String invalid : new String[]{"+160", "1e2", "NaN", ".5", "1."}) reject("Policy list:\nDisplayPolicy{packageName='p', appDpi=" + invalid + "}", "Unknown policy row value");
        if (args.length > 0) {
            String dump = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8);
            Pattern rowPattern = pattern(engine, "POLICY_ROW_PATTERN");
            Matcher legacy = Pattern.compile("DisplayPolicy\\{([^{}]*)\\}").matcher(dump.substring(dump.indexOf("Policy list:")));
            Matcher optimized = rowPattern.matcher(dump.substring(dump.indexOf("Policy list:")));
            int count = 0;
            while (legacy.find()) { check(optimized.find() && legacy.group(1).equals(optimized.group(1)), "legacy row/group equivalence"); count++; }
            check(!optimized.find(), "no extra optimized rows");
            check(parse(dump).length() == count && count > 0, "actual dump preserves row count: " + count);
        }
        System.out.println("PASS " + checks + " host-only policy-row equivalence/type/malformed/duplicate checks; no phone access.");
    }
    private static Pattern pattern(Class<?> engine, String name) throws Exception { Field field = engine.getDeclaredField(name); field.setAccessible(true); return (Pattern)field.get(null); }
    private static JSONObject parse(String dump) throws Exception {
        try { return (JSONObject)parse.invoke(null, dump); }
        catch (InvocationTargetException failure) { Throwable cause = failure.getTargetException(); if (cause instanceof Exception) throw (Exception)cause; throw failure; }
    }
    private static void reject(String dump, String message) throws Exception {
        try { parse(dump); throw new AssertionError("Malformed input accepted"); }
        catch (java.io.IOException expected) { check(expected.getMessage().contains(message), "guard retained: " + message); }
    }
    private static void check(boolean okay, String detail) { if (!okay) throw new AssertionError(detail); checks++; }
}
