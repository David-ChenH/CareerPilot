import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17202a",
        muted: "#667085",
        line: "#d9dee7",
        surface: "#ffffff",
        canvas: "#f5f7fa",
        teal: {
          700: "#0f766e",
          800: "#115e59"
        },
        amber: {
          50: "#fffbeb",
          600: "#b45309"
        },
        rose: {
          50: "#fff1f2",
          700: "#be123c"
        }
      },
      boxShadow: {
        panel: "0 10px 30px rgba(16, 24, 40, 0.06)"
      }
    }
  },
  plugins: []
} satisfies Config;
