import type { Config } from "tailwindcss";

/**
 * Design tokens - "Clinical Teal + Deep Navy". Every page and component takes its colours from here (and from the CSS
 * variables in src/index.css), so there are no per-page colour schemes. Existing utility classes keep working because the
 * default `slate` / `purple` / `indigo` scales are re-mapped instead of being renamed throughout the code base.
 */
const teal = { 50: "#F2FAF7", 100: "#E2F3F0", 200: "#BFE3DD", 300: "#8ACBC2", 400: "#3FA89D", 500: "#14877D", 600: "#0F766E", 700: "#115E59", 800: "#134E4A", 900: "#0F3D3A" };
const amberScale = { 50: "#FFF7ED", 100: "#FFF3E0", 200: "#FDE3B8", 300: "#FBBF24", 400: "#F59E0B", 500: "#D97706", 600: "#B45309", 700: "#B45309", 800: "#92400E", 900: "#78350F" };
const redScale = { 50: "#FEF5F5", 100: "#FDECEC", 200: "#F9CFCF", 300: "#F0A3A3", 400: "#E06666", 500: "#C93232", 600: "#B91C1C", 700: "#B91C1C", 800: "#991B1B", 900: "#7F1D1D" };
const blue = { 50: "#EFF6FF", 100: "#DBEAFE", 200: "#BFDBFE", 300: "#93C5FD", 400: "#60A5FA", 500: "#3B82F6", 600: "#2563EB", 700: "#1D4ED8", 800: "#1E40AF", 900: "#1E3A8A" };

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"], mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "monospace"] },
      fontSize: { base: ["0.9375rem", "1.55rem"], sm: ["0.8125rem", "1.25rem"], xs: ["0.75rem", "1.1rem"] },
      borderRadius: { lg: "10px", xl: "12px" },
      colors: {
        slate: { 50: "#F5F8FA", 100: "#F1F5F7", 200: "#DCE5EA", 300: "#C6D2DA", 400: "#83919C", 500: "#6B7C89", 600: "#536574", 700: "#3F5260", 800: "#263E4E", 900: "#172D3B" },
        brand: teal,
        purple: teal,
        indigo: blue,
        blue,
        green: { 50: "#F1FAF3", 100: "#E8F5E9", 200: "#C5E6C9", 300: "#95D0A0", 400: "#4FAE66", 500: "#2E9150", 600: "#15803D", 700: "#15803D", 800: "#166534", 900: "#14532D" },
        amber: { 50: "#FFF7ED", 100: "#FFF3E0", 200: "#FDE3B8", 300: "#FBBF24", 400: "#F59E0B", 500: "#D97706", 600: "#B45309", 700: "#B45309", 800: "#92400E", 900: "#78350F" },
        red: { 50: "#FEF5F5", 100: "#FDECEC", 200: "#F9CFCF", 300: "#F0A3A3", 400: "#E06666", 500: "#C93232", 600: "#B91C1C", 700: "#B91C1C", 800: "#991B1B", 900: "#7F1D1D" },
        orange: amberScale,
        rose: redScale,
        external: { surface: "#FFF7ED", border: "#F59E0B" },
      },
      keyframes: { shimmer: { "100%": { transform: "translateX(100%)" } }, "fade-up": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } } },
      animation: { "fade-up": "fade-up 160ms ease-out both" },
    },
  },
  plugins: [],
} satisfies Config;
