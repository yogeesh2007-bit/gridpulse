/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      colors: {
        // brand: an electric green-teal
        brand: {
          50: "#ecfdf7", 100: "#d1fae9", 200: "#a7f3d6", 300: "#6ee7bd", 400: "#34d39e",
          500: "#10b981", 600: "#059669", 700: "#047857", 800: "#065f46", 900: "#064e3b",
        },
        ink: { 950: "#070b10", 900: "#0b1219", 850: "#0f1822", 800: "#141f2b", 700: "#1c2a39", 600: "#2a3b4d" },
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,.05), 0 6px 18px -6px rgba(15,23,42,.08)",
        pop: "0 10px 30px -10px rgba(15,23,42,.35)",
      },
      keyframes: {
        pulseDot: { "0%,100%": { opacity: 1 }, "50%": { opacity: 0.35 } },
        slideUp: { from: { opacity: 0, transform: "translateY(8px)" }, to: { opacity: 1, transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        pulseDot: "pulseDot 1.6s ease-in-out infinite",
        slideUp: "slideUp .25s ease-out both",
      },
    },
  },
  plugins: [],
};
