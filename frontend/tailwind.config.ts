import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // shadcn semantic tokens (HSL CSS vars set in globals.css)
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        // UMB official blue scale
        umb: {
          100: "#EFF6FF", 200: "#DBEAFE", 300: "#BFDBFE", 400: "#93C5FD", 500: "#60A5FA",
          600: "#3B82F6", 700: "#2563EB", 800: "#1E3A8A", 900: "#172554",
        },
        success: "#16A34A", warning: "#F59E0B", error: "#DC2626", info: "#0284C7",
        // legacy tokens — remapped to theme CSS vars so they adapt to dark mode
        // (previously hardcoded light hex, which made text-ink/bg-panel/border-line
        // unreadable in dark mode). brand stays the UMB accent.
        ink: "hsl(var(--foreground))",
        panel: "hsl(var(--muted))",
        line: "hsl(var(--border))",
        brand: "hsl(var(--primary))", mango: "#d97706", skysoft: "#e0f2fe",
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
