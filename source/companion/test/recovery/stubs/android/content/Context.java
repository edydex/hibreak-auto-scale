package android.content;
import android.content.pm.PackageManager;
public final class Context {
    public static boolean dumpGranted = true;
    public int checkSelfPermission(String permission) { return dumpGranted ? PackageManager.PERMISSION_GRANTED : -1; }
    public PackageManager getPackageManager() { return new PackageManager(); }
    public Object getContentResolver() { return null; }
}
