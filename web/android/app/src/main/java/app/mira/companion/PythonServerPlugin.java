package app.mira.companion;

import android.util.Log;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import com.chaquo.python.Python;
import com.chaquo.python.AndroidPlatform;

@CapacitorPlugin(name = "PythonServer")
public class PythonServerPlugin extends Plugin {
    private static final String TAG = "PythonServer";
    private static boolean started = false;

    @PluginMethod
    public void start(PluginCall call) {
        if (started) {
            JSObject ret = new JSObject();
            ret.put("status", "already_running");
            call.resolve(ret);
            return;
        }

        String dataDir = call.getString("dataDir",
                getContext().getFilesDir().getAbsolutePath() + "/mira");
        int port = call.getInt("port", 8000);

        new Thread(() -> {
            try {
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(getContext()));
                }

                Python py = Python.getInstance();
                py.getModule("mira_mobile.main").call("start", dataDir, port);

                started = true;
                Log.i(TAG, "Python backend started on port " + port);

                JSObject ret = new JSObject();
                ret.put("status", "running");
                ret.put("port", port);
                call.resolve(ret);
            } catch (Exception e) {
                Log.e(TAG, "Failed to start Python", e);
                call.reject("Failed to start Python backend: " + e.getMessage(), e);
            }
        }, "python-start").start();
    }

    @PluginMethod
    public void stop(PluginCall call) {
        started = false;
        try {
            Python py = Python.getInstance();
            py.getModule("mira_mobile.main").call("stop");
        } catch (Exception e) {
            Log.w(TAG, "Stop failed (may already be stopped)", e);
        }
        JSObject ret = new JSObject();
        ret.put("status", "stopped");
        call.resolve(ret);
    }

    @PluginMethod
    public void status(PluginCall call) {
        JSObject ret = new JSObject();
        ret.put("running", started);
        call.resolve(ret);
    }
}
