package xrz.framework.manager;

/** Host-only fake with the actual firmware's relevant private field names. */
public final class DisplayPolicy {
    private int appDpi = 32;
    private int isDpiSetting = 0;
    private int appTextEnhance = 4;

    public void set(String field, int value) throws Exception {
        java.lang.reflect.Field target = getClass().getDeclaredField(field);
        target.setAccessible(true);
        target.setInt(this, value);
    }
}
