package android.util;
/** Host-only log sink; never included in APK input sources. */
public final class Log {
    public static int i(String tag, String message) { return 0; }
}
