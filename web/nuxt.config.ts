// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2026-11-23',

  // SSR pour les pages de contenu : elles doivent etre indexables. La carte et la 3D
  // sont montees cote client uniquement, dans des composants .client.vue.
  ssr: true,

  modules: ['@nuxt/eslint'],

  // Les composants sont en francais, dans app/composants/ : `pathPrefix: false` evite
  // d'avoir a ecrire <Composants3dJauge> pour un fichier range dans un sous-dossier.
  components: [{ path: '~/composants', pathPrefix: false }],

  css: ['~/styles/polices.css', '~/styles/tokens.css', '~/styles/base.css'],

  typescript: {
    strict: true,
    typeCheck: false, // `pnpm typecheck` le fait, pas le build de developpement
  },

  app: {
    head: {
      htmlAttrs: { lang: 'fr' },
      meta: [
        { charset: 'utf-8' },
        {
          name: 'viewport',
          content: 'width=device-width, initial-scale=1, viewport-fit=cover',
        },
        // Une seule couleur de theme ne peut pas suivre les deux themes : on la
        // declare pour chacun.
        {
          name: 'theme-color',
          content: '#f6f1e8',
          media: '(prefers-color-scheme: light)',
        },
        {
          name: 'theme-color',
          content: '#1c1714',
          media: '(prefers-color-scheme: dark)',
        },
      ],
      link: [
        // Seule la police des prix est prechargee : les autres arrivent en `swap`.
        // La paire retenue apres validation remplacera celle-ci.
        {
          rel: 'preload',
          as: 'font',
          type: 'font/woff2',
          href: '/polices/newsreader-latin-wght-normal.woff2',
          crossorigin: 'anonymous',
        },
      ],
    },
  },

  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE ?? 'http://localhost:8000',
    },
  },

  // Rien de superflu dans le bundle : le budget de l'accueil est de ~100 Ko gzip
  // hors carte et 3D.
  features: { inlineStyles: false },

  nitro: {
    compressPublicAssets: { gzip: true, brotli: true },
  },
})
