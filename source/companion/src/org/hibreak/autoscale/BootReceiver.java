package org.hibreak.autoscale;

import android.content.*;
import android.os.Build;

public final class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction()) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(intent.getAction())) return;
        try {
            if (!StateStore.workNeeded(new StateStore(context).load()) && !AutoScaleService.automaticEnabled(context)) return;
            Intent service = new Intent(context, AutoScaleService.class).setAction(AutoScaleService.REFRESH);
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(service); else context.startService(service);
        } catch (Exception ignored) {}
    }
}
