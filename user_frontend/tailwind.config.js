/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          // 暗房影院：放映机琥珀（与 --au-primary 同一色相）
          50: '#fbf3e6',
          100: '#f6e3c3',
          200: '#efcd94',
          300: '#ecbb6c',
          400: '#e8a84a',
          500: '#d4923a',
          600: '#a86f24',
          700: '#7f541b',
          800: '#573914',
          900: '#2f1f0b',
        },
        accent: {
          // 只有一支强调色：紫 / 粉并入琥珀，语义绿降饱和
          purple: '#e8a84a',
          pink: '#d4923a',
          emerald: '#8fbf8a',
          amber: '#e8a84a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
