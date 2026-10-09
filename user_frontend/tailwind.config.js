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
  // .container 是 aurora.css 的页面骨架（max-width 1080 + gutter）。Tailwind 自带的同名组件
  // 在 ≥1280px 会把 max-width 改成 1280、在样式表里还排在后面——宽屏下首页主体比顶栏宽一截、
  // 贴着屏幕左右边。全站没有用 Tailwind 的 container 语义，直接关掉
  corePlugins: {
    container: false,
  },
  plugins: [],
}
