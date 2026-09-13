/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1a1d21",
        panel: "#ffffff",
        surface: "#f4f5f7",
        border: "#dfe3e8",
        muted: "#5f6773",
        accent: "#1f4e8c",
        good: "#1e7a34",
        warn: "#b5760a",
        bad: "#b3261e",
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "Arial", "sans-serif"],
      },
    },
  },
  plugins: [],
};
