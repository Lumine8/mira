package app.mira.companion;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(PythonServerPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
