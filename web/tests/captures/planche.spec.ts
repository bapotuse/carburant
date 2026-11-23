import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'

/**
 * Captures de la planche de style du Jalon 0, et verifications qui n'ont de sens que
 * dans un vrai navigateur : chiffres tabulaires, taille des cibles tactiles, absence
 * de defilement horizontal.
 */

const JALON = process.env.JALON ?? 'J0'
const PAIRES = ['A', 'B', 'C'] as const
const THEMES = ['clair', 'sombre'] as const

async function dossier(): Promise<string> {
  const chemin = join(import.meta.dirname, '../../../docs/captures', JALON)
  await mkdir(chemin, { recursive: true })
  return chemin
}

for (const paire of PAIRES) {
  for (const theme of THEMES) {
    test(`planche de style — paire ${paire}, thème ${theme}`, async ({ page }, infos) => {
      await page.goto(`/planche-de-style?paire=${paire}&theme=${theme}`)
      await page.evaluate(() => document.fonts.ready)
      // Laisse la transition de l'aiguille de la jauge se terminer.
      await page.waitForTimeout(500)

      const appareil = infos.project.name
      await page.screenshot({
        path: join(await dossier(), `planche-${paire}-${theme}-${appareil}.png`),
        fullPage: true,
      })
    })
  }
}

test('accueil', async ({ page }, infos) => {
  for (const theme of THEMES) {
    await page.goto('/')
    await page.emulateMedia({ colorScheme: theme === 'sombre' ? 'dark' : 'light' })
    await page.evaluate(() => document.fonts.ready)
    await page.screenshot({
      path: join(await dossier(), `accueil-${theme}-${infos.project.name}.png`),
      fullPage: true,
    })
  }
})

test('les prix sont alignés au millième : les chiffres sont tabulaires', async ({ page }) => {
  await page.goto('/planche-de-style?paire=A')
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(300)

  // Les quatre prix de la liste doivent commencer exactement à la même abscisse ET
  // avoir la même largeur par chiffre. On compare la largeur d'un prix à trois
  // chiffres identiques : sans chiffres tabulaires, elle differerait.
  const largeurs = await page
    .locator('.planche__ligne-prix .prix__valeur')
    .evaluateAll((elements) => elements.map((e) => e.getBoundingClientRect().width))
  expect(largeurs.length).toBe(4)
  const ecart = Math.max(...largeurs) - Math.min(...largeurs)
  // Tous les prix affichés ont 4 chiffres (x,xxx) : largeurs identiques attendues.
  expect(ecart, `largeurs mesurées : ${largeurs.join(', ')}`).toBeLessThan(1)
})

test('aucune cible interactive sous 44 px', async ({ page }) => {
  await page.goto('/planche-de-style')
  await page.evaluate(() => document.fonts.ready)
  const trop_petites = await page
    .locator('button, a[href], input, [role="slider"]')
    .evaluateAll((elements) =>
      elements
        .map((e) => {
          const r = e.getBoundingClientRect()
          return {
            balise: e.tagName,
            texte: (e.textContent ?? '').trim().slice(0, 30),
            h: r.height,
            l: r.width,
          }
        })
        .filter((c) => c.h > 0 && (c.h < 44 || c.l < 44)),
    )
  expect(trop_petites, JSON.stringify(trop_petites, null, 2)).toEqual([])
})

test('aucun défilement horizontal', async ({ page }) => {
  for (const chemin of ['/', '/planche-de-style']) {
    await page.goto(chemin)
    await page.evaluate(() => document.fonts.ready)
    const debordement = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(debordement, `${chemin} déborde de ${debordement} px`).toBeLessThanOrEqual(0)
  }
})
