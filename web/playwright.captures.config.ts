import { existsSync } from 'node:fs'
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

const CHROMIUM_DE_L_IMAGE = '/opt/pw-browsers/chromium'
const chromiumDeLImage =
  process.env.PW_CHROMIUM ?? (existsSync(CHROMIUM_DE_L_IMAGE) ? CHROMIUM_DE_L_IMAGE : undefined)

export default defineConfig({
  testDir: './tests/captures',
  outputDir: '../docs/captures/.playwright',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],

  use: {
    baseURL: process.env.BASE_URL ?? 'http://127.0.0.1:3000',
    // Quel Chromium lancer.
    //
    // Playwright n'accepte que le numero de build qu'il a lui-meme epingle : avec
    // 1.65.1 il reclame `chromium_headless_shell-1255`. L'image de developpement de
    // cet environnement fournit le build 1243, et le telechargement y est coupe
    // (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD`). Sans cette ligne, chaque test echoue sur
    // « Executable doesn't exist ».
    //
    // On lui designe donc le binaire present : `PW_CHROMIUM` s'il est fourni, sinon
    // celui de l'image s'il existe. Sur une machine de developpement ordinaire,
    // aucun des deux n'existe et Playwright utilise le sien, comme prevu.
    launchOptions: chromiumDeLImage
      ? { executablePath: chromiumDeLImage, args: ['--no-sandbox'] }
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
        // Jamais de réutilisation. `make captures` reconstruit `.output` juste avant,
        // et un serveur déjà lancé sert l'ancienne version : les captures montrent
        // alors un site qui n'existe plus, et les tests échouent sur du code corrigé.
        // Mesuré : c'est exactement ce qui est arrivé le 24/11/2026.
        // Pour viser un serveur lancé à la main, passer `BASE_URL`.
        reuseExistingServer: false,
        timeout: 60_000,
        env: {
          NITRO_PORT: '3000',
          NITRO_HOST: '127.0.0.1',
          // Le rendu serveur et le navigateur ne joignent pas l'API par la meme
          // adresse en production ; en local les deux valent 127.0.0.1:8000.
          NUXT_API_BASE_INTERNE: process.env.NUXT_API_BASE_INTERNE ?? 'http://127.0.0.1:8000',
          NUXT_PUBLIC_API_BASE: process.env.NUXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000',
        },
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
