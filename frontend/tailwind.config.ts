import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1f2933",
        panel: "#f7f5f0",
        line: "#d8d1c2",
        brand: "#0f766e",
        mango: "#d97706",
        skysoft: "#e0f2fe"
      }
    }
  },
  plugins: []
};

export default config;

