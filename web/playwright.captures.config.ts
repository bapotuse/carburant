import { defineConfig, devices } from '@playwright/test'

/**
 * Configuration des captures de la planche de style et des pages.
 *
 * Trois cibles imposees par CLAUDE.md : iPhone SE 375x667, Pixel 7, bureau 1440x900,
 * dans les deux themes. C'est de l'EMULATION, pas un appareil reel : le test sur le
 * vrai iPhone de Baptiste est fait par lui aux points de validation.
 *
 * Les captures atterrissent dans docs/captures/<jalon>/ et seule la derniere serie de
 * chaque jalon est conservee.
 */
const JALON = process.env.JALON ?? 'J0'

export default defineConfig({
  testDir: './tests/captures',
  outputDir: '../docs/captures/.playwright',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],

  use: {
    baseURL: process.env.BASE_URL ?? 'http://127.0.0.1:3000',
    // `PW_CHROMIUM` permet d'utiliser un Chromium deja present dans l'image
    // (conteneurs, CI) plutot que d'en telecharger un. Non defini, Playwright
    // utilise le sien, ce qui est le cas sur une machine de developpement.
    launchOptions: process.env.PW_CHROMIUM
      ? { executablePath: process.env.PW_CHROMIUM, args: ['--no-sandbox'] }
      : undefined,
    // Les captures sont regardees par un humain : deux fois la densite.
    deviceScaleFactor: 2,
    locale: 'fr-FR',
    timezoneId: 'Europe/Paris',
  },

  // Le serveur de previsualisation sert la vraie sortie de build, pas le mode dev :
  // les captures doivent montrer ce que verra un visiteur.
  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: 'node .output/server/index.mjs',
        url: 'http://127.0.0.1:3000',
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
        env: { NITRO_PORT: '3000', NITRO_HOST: '127.0.0.1' },
      },

  projects: [
    {
      // ATTENTION : c'est Chromium aux metriques de l'iPhone SE, pas WebKit.
      // Le profil `devices['iPhone SE']` de Playwright utilise WebKit, qui n'est pas
      // installe dans tous les environnements de construction. Les differences qui
      // comptent vraiment -- zoom au focus des champs, `safe-area-inset`, absence de
      // `navigator.vibrate`, politique de geolocalisation -- ne sont donc PAS
      // couvertes ici. C'est Baptiste qui teste sur son vrai iPhone aux points de
      // validation. Voir docs/a-verifier.md.
      name: 'iphone-se',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 375, height: 667 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
      },
      metadata: { jalon: JALON, emulation: 'chromium aux metriques iPhone SE' },
    },
    {
      name: 'pixel-7',
      use: { ...devices['Pixel 7'] },
      metadata: { jalon: JALON },
    },
    {
      name: 'bureau',
      use: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 },
      metadata: { jalon: JALON },
    },
  ],
})
