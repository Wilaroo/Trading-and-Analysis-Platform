/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#050505',
        paper: '#0A0A0A',
        subtle: '#121212',
        primary: {
          DEFAULT: '#00E5FF',
          hover: '#33EBFF',
          glow: 'rgba(0, 229, 255, 0.15)',
        },
        success: '#00FF94',
        warning: '#FFD600',
        error: '#FF2E2E',
        info: '#2979FF',
        border: {
          DEFAULT: 'rgba(255, 255, 255, 0.08)',
          active: 'rgba(0, 229, 255, 0.3)',
        },
      },
      fontFamily: {
        sans: ['Manrope', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
        editorial: ['Playfair Display', 'serif'],
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)'
      }
    }
  },
  plugins: [require("tailwindcss-animate")],
}
