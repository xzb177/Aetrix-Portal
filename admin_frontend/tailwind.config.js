/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 使用 CSS 变量作为颜色源
        bg: {
          base: 'var(--bg-base)',
          surface: 'var(--bg-surface)',
          card: 'var(--bg-card)',
          'card-hover': 'var(--bg-card-hover)',
          input: 'var(--bg-input)',
          overlay: 'var(--bg-overlay)',
        },
        text: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          tertiary: 'var(--text-tertiary)',
          inverse: 'var(--text-inverse)',
        },
        primary: {
          DEFAULT: 'var(--primary)',
          hover: 'var(--primary-hover)',
          active: 'var(--primary-active)',
          on: 'var(--primary-on)',
        },
        success: {
          DEFAULT: 'var(--success)',
          bg: 'var(--success-bg)',
        },
        warning: {
          DEFAULT: 'var(--warning)',
          bg: 'var(--warning-bg)',
        },
        danger: {
          DEFAULT: 'var(--danger)',
          bg: 'var(--danger-bg)',
        },
        info: {
          DEFAULT: 'var(--info)',
          bg: 'var(--info-bg)',
        },
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
        '2xl': 'var(--radius-2xl)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
        glow: 'var(--shadow-glow)',
      },
      backdropBlur: {
        md: 'var(--blur-md)',
        lg: 'var(--blur-lg)',
      },
      spacing: {
        'touch': 'var(--touch-target-min)',
        'list-item': 'var(--list-item-min)',
      },
      transitionDuration: {
        'fast': '150ms',
        'base': '250ms',
        'slow': '350ms',
      },
      transitionTimingFunction: {
        'bounce-out': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
      minHeight: {
        'touch': 'var(--touch-target-min)',
        'list-item': 'var(--list-item-min)',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    // 添加自定义工具类
    function({ addUtilities, addComponents }) {
      // 触控反馈
      addComponents({
        '.touch-feedback': {
          'transition': 'transform 150ms ease, opacity 150ms ease',
          '&:active': {
            'transform': 'scale(0.97)',
            'opacity': '0.85',
          },
        },
      });

      // 玻璃卡片
      addUtilities({
        '.glass-card': {
          'background': 'var(--glass-surface)',
          'backdrop-filter': 'var(--blur-md)',
          '-webkit-backdrop-filter': 'var(--blur-md)',
          'border': '1px solid var(--glass-border)',
        },
      });
    },
  ],
}
