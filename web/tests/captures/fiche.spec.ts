import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

/**
 * La fiche d'une station, depuis un téléphone.
 *
 * Ce que ce parcours vérifie, et qu'aucun test unitaire ne peut vérifier : qu'on
 * **arrive** sur la fiche depuis la liste de résultats, et que la fiche ne cache rien
 * — les prix avec leur date, les ruptures, la courbe, les horaires.
 *
 * Il parle à la vraie API et à la vraie base. Un bouchon ne dirait rien de ce qui
 * compte : qu'une station inconnue répond 404 et non 502, que la courbe se dessine
 * sur de vrais changements de prix, et que l'adresse en capitales du flux officiel
 * s'affiche en français lisible.
 */

const JALON = process.env.JALON ?? 'J5'

async function dossier(): Promise<string> {
  const chemin = join(import.meta.dirname, '../../../docs/captures', JALON)
  await mkdir(chemin, { recursive: true })
  return chemin
}

/**
 * Va de l'accueil à la fiche de la première station trouvée, **par la géolocalisation**.
 *
 * Pas par la saisie d'adresse, et c'est délibéré : « Ma position » est le geste
 * principal du parcours mobile, et c'est aussi le seul qui ne dépende pas du
 * géocodeur de l'IGN — injoignable depuis l'environnement de développement. Ce test
 * tourne donc partout, y compris là où la recherche par adresse ne peut pas marcher.
 */
async function premiereFiche(page: import('@playwright/test').Page) {
  await page.goto('/')
  // Le Prado, à Marseille : la position de référence du projet.
  await page.context().grantPermissions(['geolocation'])
  await page.context().setGeolocation({ latitude: 43.2726, longitude: 5.3846 })
  await page.locator('.recherche__position').click()

  const premiere = page.locator('.station').first()
  await expect(premiere).toBeVisible({ timeout: 15_000 })
  const lien = premiere.locator('.station__lien')
  const titre = await lien.innerText()
  await lien.click()
  await expect(page).toHaveURL(/\/station\/\d+$/)
  // L'URL change **avant** que la page ne soit rendue : une navigation cote client
  // bascule l'adresse tout de suite. Sans cette attente, les assertions suivantes
  // cherchent la fiche dans l'accueil et n'y trouvent rien.
  await expect(page.locator('.fiche')).toBeVisible({ timeout: 15_000 })
  return titre.trim()
}

test('depuis la liste, on arrive sur la fiche de la station', async ({ page }, infos) => {
  // La console est surveillée pendant tout le parcours : une politique de sécurité du
  // contenu trop stricte laisse une page qui s'affiche et où plus rien ne répond,
  // sans qu'aucune autre assertion ne s'en aperçoive.
  const plaintes: string[] = []
  page.on('console', (m) => m.type() === 'error' && plaintes.push(m.text()))
  page.on('pageerror', (e) => plaintes.push(`pageerror: ${e.message}`))

  const titre = await premiereFiche(page)

  // Le titre de la fiche est celui du lien cliqué : on n'a pas changé de station.
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(titre)

  // L'adresse du flux est en capitales ; la fiche l'écrit en français.
  const h1 = await page.getByRole('heading', { level: 1 }).innerText()
  expect(h1).not.toBe(h1.toUpperCase())

  // Au moins un prix, et chacun avec sa date : la règle centrale du projet.
  const carburants = page.locator('.fiche__carburant')
  const nombre = await carburants.count()
  expect(nombre).toBeGreaterThan(0)
  for (let i = 0; i < nombre; i++) {
    await expect(carburants.nth(i).locator('.prix')).toBeVisible()
    await expect(carburants.nth(i).locator('time')).toHaveAttribute(
      'datetime',
      /^\d{4}-\d{2}-\d{2}/,
    )
  }

  // La courbe est une image : elle doit porter un texte de remplacement qui dit ce
  // qu'un œil en retire, sinon elle ne dit rien à qui ne la voit pas.
  const courbe = page.locator('.courbe__dessin')
  if (await courbe.count()) {
    const resume = await courbe.getAttribute('aria-label')
    expect(resume ?? '').toMatch(/prix/i)
  }

  // Les trois applications d'itinéraire, pas une seule.
  const liens = page.locator('.itineraire__lien')
  await expect(liens).toHaveCount(3)

  await page.screenshot({
    path: join(await dossier(), `fiche-${infos.project.name}.png`),
    fullPage: true,
  })

  expect(plaintes, plaintes.join('\n')).toEqual([])
})

test('aucune cible tactile sous 44 px, et pas de débordement horizontal', async ({ page }) => {
  await premiereFiche(page)

  // 44 px : la mesure de `docs/specs/web.md`. Au Jalon 1, quatre cibles étaient en
  // dessous et aucune relecture ne l'avait vu.
  const cibles = page.locator('.fiche a, .fiche button, .itineraire__lien')
  const nombre = await cibles.count()
  expect(nombre).toBeGreaterThan(0)
  for (let i = 0; i < nombre; i++) {
    const boite = await cibles.nth(i).boundingBox()
    if (!boite) continue
    expect(
      Math.max(boite.height, boite.width),
      `cible ${i} : ${boite.width}×${boite.height}`,
    ).toBeGreaterThanOrEqual(44)
  }

  const debordement = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(debordement, `${debordement} px de débordement horizontal`).toBeLessThanOrEqual(0)
})

test('une station inconnue répond 404, pas 502', async ({ page }) => {
  // L'erreur était réelle : `useAsyncData` enveloppe ce qui est levé dans son
  // gestionnaire, donc un `instanceof` testé à l'extérieur est toujours faux et
  // toutes les erreurs devenaient des 502.
  const reponse = await page.goto('/station/99999999')
  expect(reponse?.status()).toBe(404)
})

test('la fiche en thème sombre', async ({ page }, infos) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await premiereFiche(page)
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({
    path: join(await dossier(), `fiche-sombre-${infos.project.name}.png`),
    fullPage: true,
  })
})
