import js from '@eslint/js'
import globals from 'globals'
import i18next from 'eslint-plugin-i18next'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import prettier from 'eslint-config-prettier'

export default tseslint.config(
  { ignores: ['dist', 'coverage'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        project: ['./tsconfig.app.json', './tsconfig.node.json'],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      i18next,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Project convention: TS strict, no `any`.
      '@typescript-eslint/no-explicit-any': 'error',
      // Spec §9 hard rule (gate-checked): no hardcoded user-visible strings —
      // every JSX text node and visible attribute must come from useT()/the
      // dictionaries. Non-visible props (className, ids, routes…) are exempt
      // via the attribute include-list; letterless strings (punctuation,
      // separators) are exempt via words.exclude.
      'i18next/no-literal-string': [
        'error',
        {
          mode: 'jsx-only',
          'jsx-attributes': {
            include: ['label', 'aria-label', 'aria-description', 'alt', 'placeholder', 'title'],
          },
          words: {
            exclude: ['^[^A-Za-zÀ-ÿ]*$'],
          },
        },
      ],
    },
  },
  {
    // Tests and the dictionaries themselves legitimately contain raw strings.
    files: ['**/*.test.{ts,tsx}', 'src/i18n/it.ts', 'src/i18n/en.ts'],
    rules: {
      'i18next/no-literal-string': 'off',
    },
  },
  prettier,
)
