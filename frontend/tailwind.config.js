/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Make the default border AND divide color follow the CSS variable,
      // so elements using plain `border`, `divide-y`, `border-b` etc. pick
      // up a soft grey instead of Tailwind's library default (gray-200,
      // which renders as a harsh white line on the dark theme).
      borderColor: {
        DEFAULT: 'var(--border-color)',
      },
      divideColor: {
        DEFAULT: 'var(--border-color)',
      },
      colors: {
        // Theme-aware tokens backed by CSS variables in index.css. These make
        // classes like `bg-card`, `bg-tertiary`, `text-accent-primary`,
        // `border-border`, `placeholder-muted` etc. respect the active theme
        // (peec / light / dark) instead of resolving to hardcoded shades.
        border: 'var(--border-color)',
        'border-strong': 'var(--border-strong)',
        card: 'var(--bg-card)',
        tertiary: 'var(--bg-tertiary)',
        surface: 'var(--bg-surface)',
        'surface-hover': 'var(--bg-surface-hover)',
        'accent-primary': 'var(--accent-primary)',
        'accent-secondary': 'var(--accent-secondary)',
        muted: 'var(--text-muted)',
        primary: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
        },
        secondary: {
          50: '#ecfeff',
          100: '#cffafe',
          200: '#a5f3fc',
          300: '#67e8f9',
          400: '#22d3ee',
          500: '#06b6d4',
          600: '#0891b2',
          700: '#0e7490',
          800: '#155e75',
          900: '#164e63',
        },
      },
      animation: {
        'spin': 'spin 1s linear infinite',
      },
      keyframes: {
        spin: {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
      },
    },
  },
  plugins: [],
}
