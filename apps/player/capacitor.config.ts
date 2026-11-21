/**
 * Phone app shell (D-011): the same player app, packaged for Android (iOS later).
 *
 * Build:   VITE_API_BASE_URL=https://api.<domain> VITE_PUBLIC_URL=https://<domain> npm run build
 *          npx cap sync android && (cd android && ./gradlew assembleDebug)
 * Local:   CAP_DEV=1 lets a debug build talk to http:// / ws:// servers on your LAN.
 *
 * appId cannot change after the first Play Store upload - settle the brand (O-5) first.
 */
import type { CapacitorConfig } from "@capacitor/cli";

const dev = process.env.CAP_DEV === "1";

const config: CapacitorConfig = {
  appId: "app.feltkings.player",
  appName: "Draely",
  webDir: "dist",
  backgroundColor: "#030c08",
  server: {
    androidScheme: "https", // origin https://localhost (allowed by the API's CORS list)
    cleartext: dev,
  },
  android: {
    allowMixedContent: dev,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 3000,
      launchAutoHide: true,
      backgroundColor: "#030c08",
      showSpinner: false,
      androidScaleType: "CENTER_INSIDE",
    },
  },
};

export default config;
