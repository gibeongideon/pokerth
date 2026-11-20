/** Design tokens for the gamey look (D-020). Mirrored as CSS variables in
 * src/styles.css so PixiJS and plain CSS use the same values. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        felt: { 950: "#04120c", 900: "#071a13", 800: "#0b2a1f", 700: "#0f3a2a", 600: "#116149", 500: "#178a62" },
        gold: { 300: "#ffe08a", 400: "#f5c451", 500: "#e2a72e", 600: "#b9821a" },
        cream: "#f6f1e3",
        chip: { red: "#e0464b", blue: "#3d7be0", green: "#35b26b", purple: "#8f5ce0", black: "#1c1c22" },
      },
      fontFamily: {
        display: ['"Lilita One"', "system-ui", "sans-serif"],
        sans: ['"Inter Variable"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(245,196,81,.35), 0 0 24px rgba(245,196,81,.18)",
        panel: "0 10px 30px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.06)",
      },
      keyframes: {
        pop: { "0%": { transform: "scale(.6)", opacity: "0" }, "70%": { transform: "scale(1.06)" }, "100%": { transform: "scale(1)", opacity: "1" } },
        pulseGlow: { "0%,100%": { boxShadow: "0 0 0 0 rgba(245,196,81,.55)" }, "50%": { boxShadow: "0 0 0 12px rgba(245,196,81,0)" } },
        float: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-6px)" } },
        fadeUp: { "0%": { opacity: "0", transform: "translateY(6px)" }, "100%": { opacity: "1", transform: "none" } },
        shine: { "0%": { transform: "translateX(-120%) skewX(-20deg)" }, "60%,100%": { transform: "translateX(260%) skewX(-20deg)" } },
      },
      animation: {
        pop: "pop .35s cubic-bezier(.2,.9,.3,1.3) both",
        pulseGlow: "pulseGlow 1.6s ease-out infinite",
        float: "float 3s ease-in-out infinite",
        shine: "shine 3.2s ease-in-out infinite",
        fadeUp: "fadeUp .25s ease-out both",
      },
    },
  },
  plugins: [],
};
