import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

/**
 * Le parcours « chercher une station depuis un téléphone ».
 *
 * C'est le test obligatoire de `CLAUDE.md`, et le critère de sortie du Jalon 1 :
 * depuis un téléphone, saisir « le Prado, Marseille » doit donner des stations
 * réelles, avec leur prix et leur fraîcheur.
 *
 * Il parle à la **vraie API** et à la **vraie base**, pas à des bouchons : une
 * simulation ne dirait rien de ce qui compte ici — que les prix arrivent, qu'ils
 * portent leur date, et que la liste soit triée.
 */

const JALON = process.env.JALON ?? 'J1'

async function dossier(): Promise<string> {
  const chemin = join(import.meta.dirname, '../../../docs/captures', JALON)
  await mkdir(chemin, { recursive: true })
  return chemin
}

/** Saisit une adresse et choisit un candidat dans la liste de suggestions. */
async function chercher(page: import('@playwright/test').Page, texte: string) {
  const champ = page.getByRole('combobox')
  await champ.click()
  await champ.fill(texte)
  // Les suggestions arrivent après l'anti-rebond (350 ms) et un aller-retour réseau.
  const suggestions = page.getByRole('option')
  await expect(suggestions.first()).toBeVisible({ timeout: 15_000 })
  return suggestions
}

test('le parcours complet : une adresse, puis des prix réels', async ({ page }, infos) => {
  // La console est surveillee pendant tout le parcours. Ce n'est pas du zele : une
  // politique de securite du contenu trop stricte bloque les scripts en ligne de
  // Nuxt, et le site reste une page statique ou plus rien ne repond — sans qu'aucune
  // autre assertion ne s'en apercoive tant qu'on ne touche pas aux boutons.
  const plaintes: string[] = []
  page.on('console', (m) => m.type() === 'error' && plaintes.push(m.text()))
  page.on('pageerror', (e) => plaintes.push(`pageerror: ${e.message}`))

  await page.goto('/')
  await page.evaluate(() => document.fonts.ready)

  // L'accueil annonce ce qu'il fait, sans promesse creuse.
  await expect(page.getByRole('heading', { name: /Où faire le plein/ })).toBeVisible()

  const suggestions = await chercher(page, 'le Prado, Marseille')

  // « le Prado » est ambigu : le site doit le dire et proposer, pas deviner.
  await expect(page.getByText(/Plusieurs lieux portent ce nom/)).toBeVisible()
  await page.screenshot({
    path: join(await dossier(), `accueil-suggestions-${infos.project.name}.png`),
    fullPage: true,
  })

  await suggestions.first().click()

  // Les résultats arrivent.
  const stations = page.locator('.station')
  await expect(stations.first()).toBeVisible({ timeout: 15_000 })
  const nombre = await stations.count()
  expect(nombre).toBeGreaterThan(0)

  // Chaque station affiche un prix ET sa date : la règle centrale du projet.
  for (let i = 0; i < Math.min(nombre, 5); i++) {
    const station = stations.nth(i)
    await expect(station.locator('.prix')).toBeVisible()
    await expect(station.locator('time')).toHaveAttribute('datetime', /^\d{4}-\d{2}-\d{2}/)
  }

  // La liste est triée du moins cher au plus cher.
  const prix = await stations.locator('.lecteur-seul').allInnerTexts()
  const valeurs = prix
    .map((t) => t.match(/([\d,]+) euro/)?.[1]?.replace(',', '.'))
    .filter((v): v is string => Boolean(v))
    .map(Number)
  expect(valeurs.length).toBeGreaterThan(0)
  expect([...valeurs].sort((a, b) => a - b)).toEqual(valeurs)

  await page.screenshot({
    path: join(await dossier(), `accueil-resultats-${infos.project.name}.png`),
    fullPage: true,
  })

  expect(plaintes, plaintes.join('\n')).toEqual([])
})

test('changer de carburant relance la recherche', async ({ page }) => {
  await page.goto('/')
  const suggestions = await chercher(page, '13008')
  await suggestions.first().click()
  await expect(page.locator('.station').first()).toBeVisible({ timeout: 15_000 })

  // On touche l'étiquette, pas le bouton radio : le radio est masqué visuellement
  // (il reste pour le clavier et les lecteurs d'écran) et c'est l'étiquette qui
  // porte la cible tactile de 44 px. Cliquer le radio ne reproduirait pas le geste.
  const premierPrix = await page.locator('.station .prix').first().innerText()

  await page.locator('.carburants__choix', { hasText: 'E85' }).click()
  await expect(page.getByRole('radio', { name: 'E85' })).toBeChecked()

  // La légende de la liste porte la pastille du carburant demandé.
  await expect(page.locator('.liste__compte')).toContainText('E85')

  // Et surtout, les prix ont changé : l'E85 vaut environ la moitié du gazole.
  // Sans cela, le test passerait alors que la recherche n'a pas été relancée.
  await expect(page.locator('.station .prix').first()).not.toHaveText(premierPrix, {
    timeout: 15_000,
  })
})

test("l'accueil en thème sombre", async ({ page }, infos) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto('/')
  await page.evaluate(() => document.fonts.ready)
  const suggestions = await chercher(page, '13008')
  await suggestions.first().click()
  await expect(page.locator('.station').first()).toBeVisible({ timeout: 15_000 })
  await page.screenshot({
    // « accueil-sombre » est déjà pris par planche.spec.ts, qui capture l'état
    // initial : deux tests qui écrivent le même fichier en parallèle, c'est une
    // course, et l'un des deux résultats disparaît.
    path: join(await dossier(), `accueil-resultats-sombre-${infos.project.name}.png`),
    fullPage: true,
  })
})

test('aucune cible interactive sous 44 px sur l’accueil', async ({ page }) => {
  await page.goto('/')
  await page.evaluate(() => document.fonts.ready)
  const trop_petites = await page
    .locator('button, a[href], input, label, [role="radio"], [role="option"]')
    .evaluateAll((elements) =>
      elements
        // Un contrôle masqué visuellement (`clip-path: inset(50%)`) n'est pas une
        // cible pour le doigt : il existe pour le clavier et les lecteurs d'écran,
        // et c'est son étiquette qui porte la cible — mesurée, elle aussi, ici.
        .filter((e) => !getComputedStyle(e).clipPath.startsWith('inset(50%'))
        .map((e) => {
          const r = e.getBoundingClientRect()
          return {
            balise: e.tagName,
            classe: String(e.className),
            texte: (e.textContent ?? '').trim().slice(0, 30),
            h: Math.round(r.height),
            l: Math.round(r.width),
          }
        })
        .filter((c) => c.h < 44 || c.l < 44),
    )
  expect(trop_petites, JSON.stringify(trop_petites, null, 2)).toEqual([])
})

test('aucun défilement horizontal sur l’accueil', async ({ page }) => {
  await page.goto('/')
  await page.evaluate(() => document.fonts.ready)
  const debordement = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(debordement).toBeLessThanOrEqual(0)
})

test('la géolocalisation n’est pas demandée au chargement', async ({ page }) => {
  /**
   * Une page qui demande la position à l'ouverture est une page qu'on referme.
   * Elle ne doit être demandée qu'au clic sur « Ma position ».
   */
  let demandee = false
  await page.exposeFunction('signalerDemande', () => {
    demandee = true
  })
  await page.addInitScript(() => {
    const original = navigator.geolocation.getCurrentPosition.bind(navigator.geolocation)
    navigator.geolocation.getCurrentPosition = (...args) => {
      ;(window as unknown as { signalerDemande: () => void }).signalerDemande()
      return original(...args)
    }
  })

  await page.goto('/')
  await page.waitForTimeout(1500)
  expect(demandee, 'la position a été demandée sans clic').toBe(false)

  await page.getByRole('button', { name: 'Utiliser ma position' }).click()
  await page.waitForTimeout(500)
  expect(demandee, 'le clic doit déclencher la demande').toBe(true)
})
