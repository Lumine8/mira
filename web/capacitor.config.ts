import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "app.mira.companion",
  appName: "Mira",
  webDir: "dist",
  android: {
    allowMixedContent: true,
  },
  server: {
    // The bundle is served from the app itself. Mira lives somewhere on the
    // network; the settings screen points the app at her (same spirit as the
    // single-click portable installer). Mixed content is allowed so an http://
    // Mira address works over the LAN.
    androidScheme: "https",
    cleartext: true,
  },
};

export default config;