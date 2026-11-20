/**
 * Phone-app glue (no-op on the web): deep links (invite links, sign-in links)
 * open inside the app, the Android back button navigates, and the status bar
 * and splash screen match the app.
 */
import { App as CapApp } from "@capacitor/app";
import { SplashScreen } from "@capacitor/splash-screen";
import { StatusBar, Style } from "@capacitor/status-bar";
import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { isNative, nativePlatform } from "../lib/native";

// Only these paths may be opened from outside the app.
const DEEP_LINK = /^\/(auth\/callback|i\/[A-Za-z0-9]+|join\/[A-Za-z0-9]+|tables\/[0-9a-f-]+)$/;

export function NativeBridge() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!isNative) return;
    void SplashScreen.hide();
    void StatusBar.setStyle({ style: Style.Dark });
    if (nativePlatform === "android") void StatusBar.setBackgroundColor({ color: "#030c08" });

    const open = CapApp.addListener("appUrlOpen", ({ url }) => {
      try {
        const u = new URL(url); // https://<site>/i/CODE or feltkings://i/CODE
        const path = u.protocol.startsWith("http") ? u.pathname : `/${u.host}${u.pathname}`.replace(/\/$/, "");
        if (DEEP_LINK.test(path)) navigate(path + u.search);
      } catch {
        /* ignore malformed links */
      }
    });
    return () => {
      void open.then((h) => h.remove());
    };
  }, [navigate]);

  useEffect(() => {
    if (!isNative) return;
    const back = CapApp.addListener("backButton", ({ canGoBack }) => {
      if (location.pathname === "/" || !canGoBack) void CapApp.minimizeApp();
      else navigate(-1);
    });
    return () => {
      void back.then((h) => h.remove());
    };
  }, [navigate, location.pathname]);

  return null;
}
