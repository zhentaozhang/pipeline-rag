import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  // 构建/审计脚本跑在 Node 里，用 browser globals 会把 process、fs 全判成未定义
  {
    files: ['scripts/**/*.mjs', '*.config.{js,mjs}'],
    extends: [js.configs.recommended],
    languageOptions: {
      // 审计脚本在 Node 里跑，但 page.evaluate 的函数体里会用到 DOM API
      globals: { ...globals.node, ...globals.browser },
    },
  },
])
