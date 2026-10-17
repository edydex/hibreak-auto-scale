package android.os;
/** Host-only clock; never included in APK input sources. */
public final class SystemClock {
    public static long elapsedRealtime() { return System.nanoTime() / 1000000L; }
}
