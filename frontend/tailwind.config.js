/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#F6F8FB",
        panel: "#FFFFFF",
        raised: "#EEF3F8",
        line: "#E2E8F0",
        line2: "#CBD5E1",
        paper: "#0F172A",
        muted: "#64748B",
        accent: "#0E7490",
        steel: "#2563EB",
        steel2: "#3B82F6",
        amber: "#B45309",
        danger: "#DC2626",
        success: "#059669",
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      letterSpacing: {
        label: "0.08em",
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 23, 42, 0.05), 0 8px 24px rgba(15, 23, 42, 0.06)",
      },
    },
  },
  plugins: [],
};
