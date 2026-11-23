// Configuration ESLint, construite par @nuxt/eslint depuis la config du projet.
import withNuxt from './.nuxt/eslint.config.mjs'

export default withNuxt({
  rules: {
    // Le vocabulaire metier est en francais, sans accents dans les identifiants.
    'vue/multi-word-component-names': 'off',
    // Interdit ce que la direction artistique interdit, au niveau du lint.
    'no-console': ['error', { allow: ['warn', 'error'] }],
    // Prettier est seul maitre du formatage. Sans cette ligne, eslint reecrit
    // `<hr />` en `<hr>` et prettier le reecrit en `<hr />` : les deux hooks
    // pre-commit se contredisent a l'infini.
    'vue/html-self-closing': 'off',
    'vue/first-attribute-linebreak': 'off',
    'vue/max-attributes-per-line': 'off',
    'vue/singleline-html-element-content-newline': 'off',
  },
})
