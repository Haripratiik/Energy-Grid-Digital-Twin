/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: "#090a0c",
          secondary: "#0f1115",
          tertiary: "#161a20",
          elevated: "#1d2128",
        },
        border: {
          subtle: "#252830",
          strong: "#363b47",
        },
        accent: {
          blue: "#1a6cf5",
          "blue-dim": "#1040a0",
          green: "#00c97a",
          yellow: "#f0a500",
          red: "#e53e3e",
          "red-dim": "#7a1f1f",
        },
        text: {
          primary: "#dde1e8",
          secondary: "#8a919e",
          muted: "#464c58",
          code: "#5bbcff",
        },
      },
      fontFamily: {
        mono: [
          "JetBrains Mono",
          "Fira Code",
          "Cascadia Code",
          "monospace",
        ],
        sans: ["IBM Plex Sans", "Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
