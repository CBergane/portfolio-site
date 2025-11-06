/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './home/templates/**/*.html',
    './templates/**/*.html',
    './home/templates/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        'htb-green': '#9fef00',
        'htb-cyan': '#00d9ff',
        'htb-dark': '#0a0e14',
        'htb-darker': '#050810',
        'htb-gray': '#1a1f2e',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Courier New', 'monospace'],
      },
      typography: ({ theme }) => ({
        invert: {
          css: {
            '--tw-prose-body': theme('colors.gray.300'),
            '--tw-prose-headings': theme('colors.white'),
            '--tw-prose-links': theme('colors.htb-green'),
            '--tw-prose-bold': theme('colors.white'),
            '--tw-prose-quotes': theme('colors.gray.200'),
            '--tw-prose-quote-borders': theme('colors.htb-cyan'),
            '--tw-prose-code': theme('colors.gray.100'),
            '--tw-prose-pre-bg': theme('colors.gray.900'),
            'a:hover': { color: theme('colors.htb-cyan') },
            'h1,h2,h3': { 'scroll-margin-top': '96px' }
          }
        }
      })
    },
  },
  plugins: [require('@tailwindcss/typography')],
};
