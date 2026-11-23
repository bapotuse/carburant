import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Vérifie le contraste de chaque paire de tokens réellement utilisée, dans les deux
 * thèmes — exigence de la planche de style du Jalon 0.
 *
 * Le test lit `app/styles/tokens.css` : il n'y a donc pas de valeurs recopiées à la
 * main qui pourraient dériver. Il vérifie aussi que les contrastes **écrits en
 * commentaire** dans la feuille correspondent au calcul, pour que la documentation ne
 * puisse pas mentir.
 */

const CSS = readFileSync(join(import.meta.dirname, '../../app/styles/tokens.css'), 'utf8')

// ---------------------------------------------------------------- WCAG 2.1

function canal(octet: number): number {
  const c = octet / 255
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function luminance(hex: string): number {
  const n = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16))
  return 0.2126 * canal(r!) + 0.7152 * canal(g!) + 0.0722 * canal(b!)
}

function contraste(a: string, b: string): number {
  const [la, lb] = [luminance(a), luminance(b)]
  const [haut, bas] = la > lb ? [la, lb] : [lb, la]
  return (haut + 0.05) / (bas + 0.05)
}

// ---------------------------------------------------------------- lecture des tokens

/**
 * Extrait les tokens d'un bloc de la feuille.
 * `:root { … }` donne le thème clair, `:root[data-theme='dark'] { … }` le sombre.
 */
function tokensDuBloc(selecteur: string): Record<string, string> {
  const debut = CSS.indexOf(selecteur)
  if (debut === -1) throw new Error(`sélecteur introuvable : ${selecteur}`)
  const ouvrante = CSS.indexOf('{', debut)
  let profondeur = 0
  let fin = ouvrante
  for (let i = ouvrante; i < CSS.length; i++) {
    if (CSS[i] === '{') profondeur++
    else if (CSS[i] === '}') {
      profondeur--
      if (profondeur === 0) {
        fin = i
        break
      }
    }
  }
  const corps = CSS.slice(ouvrante, fin)
  const tokens: Record<string, string> = {}
  for (const [, nom, valeur] of corps.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    tokens[nom!] = valeur!.toLowerCase()
  }
  return tokens
}

const CLAIR = tokensDuBloc(':root {')
const SOMBRE = tokensDuBloc(":root[data-theme='dark']")

const THEMES = [
  { nom: 'clair', tokens: CLAIR },
  { nom: 'sombre', tokens: SOMBRE },
] as const

/** Tokens de texte, qui doivent atteindre AA (4,5:1) sur fond ET sur surface. */
const TEXTE = ['encre', 'encre-2', 'terracotta-texte', 'olive-texte', 'ardoise']

/** Les six carburants : eux aussi servent de texte à côté de leur pastille. */
const CARBURANTS = [
  'carburant-gazole',
  'carburant-sp95',
  'carburant-e10',
  'carburant-sp98',
  'carburant-e85',
  'carburant-gplc',
]

/** Les quatre classes de fraîcheur, écrites en petit à côté de la date. */
const FRAICHEUR = ['fraicheur-frais', 'fraicheur-recent', 'fraicheur-ancien', 'fraicheur-perime']

describe.each(THEMES)('thème $nom', ({ tokens }) => {
  it('déclare tous les tokens attendus', () => {
    for (const nom of ['fond', 'surface', 'bordure', 'ligne', ...TEXTE, ...CARBURANTS]) {
      expect(tokens, `token --${nom} manquant`).toHaveProperty(nom)
    }
  })

  describe.each(TEXTE)('--%s', (nom) => {
    it.each(['fond', 'surface'])('atteint AA (4,5:1) sur --%s', (fondNom) => {
      expect(contraste(tokens[nom]!, tokens[fondNom]!)).toBeGreaterThanOrEqual(4.5)
    })
  })

  describe.each(CARBURANTS)('--%s', (nom) => {
    it.each(['fond', 'surface'])('atteint AA (4,5:1) sur --%s', (fondNom) => {
      expect(contraste(tokens[nom]!, tokens[fondNom]!)).toBeGreaterThanOrEqual(4.5)
    })
  })

  describe.each(FRAICHEUR)('--%s', (nom) => {
    it.each(['fond', 'surface'])('atteint AA (4,5:1) sur --%s', (fondNom) => {
      expect(contraste(tokens[nom]!, tokens[fondNom]!)).toBeGreaterThanOrEqual(4.5)
    })
  })

  it('--bordure atteint 3:1 : WCAG 1.4.11 pour les bordures de contrôle', () => {
    expect(contraste(tokens.bordure!, tokens.fond!)).toBeGreaterThanOrEqual(3)
    expect(contraste(tokens.bordure!, tokens.surface!)).toBeGreaterThanOrEqual(3)
  })

  it("--ligne reste sous 3:1 : c'est un token décoratif, jamais une bordure de contrôle", () => {
    expect(contraste(tokens.ligne!, tokens.fond!)).toBeLessThan(3)
  })

  it("n'emploie ni noir pur ni blanc pur", () => {
    for (const [nom, valeur] of Object.entries(tokens)) {
      expect(valeur, `--${nom} est du noir ou du blanc pur`).not.toMatch(/^#(000000|ffffff)$/)
    }
  })
})

describe('terracotta et olive, les deux pièges de la palette', () => {
  it('échouent à AA pour le texte courant : la spec le dit, on le vérifie', () => {
    expect(contraste(CLAIR['terracotta']!, CLAIR.fond!)).toBeLessThan(4.5)
    expect(contraste(CLAIR['olive']!, CLAIR.fond!)).toBeLessThan(4.5)
  })

  it('ont donc chacun une variante -texte plus sombre qui, elle, passe', () => {
    expect(contraste(CLAIR['terracotta-texte']!, CLAIR.fond!)).toBeGreaterThanOrEqual(4.5)
    expect(contraste(CLAIR['olive-texte']!, CLAIR.fond!)).toBeGreaterThanOrEqual(4.5)
  })

  it('restent utilisables en aplat : du texte encre dessus atteint 3:1', () => {
    expect(contraste(CLAIR.encre!, CLAIR['terracotta']!)).toBeGreaterThanOrEqual(3)
    expect(contraste(CLAIR.encre!, CLAIR['olive']!)).toBeGreaterThanOrEqual(3)
  })
})

describe('les six pastilles de carburant', () => {
  it('ont une luminance étalée en thème clair, pour rester distinctes en niveaux de gris', () => {
    const contrastes = CARBURANTS.map((n) => contraste(CLAIR[n]!, CLAIR.fond!))
    const etendue = Math.max(...contrastes) - Math.min(...contrastes)
    // Mesuré : de 5,13:1 (e85) à 9,47:1 (sp95), soit une étendue de 4,3.
    expect(etendue).toBeGreaterThan(3)
  })

  it('ne comptent jamais sur la seule couleur : PastilleCarburant ajoute forme et libellé', () => {
    const composant = readFileSync(
      join(import.meta.dirname, '../../app/composants/PastilleCarburant.vue'),
      'utf8',
    )
    expect(composant).toContain('cercle')
    expect(composant).toContain('carre')
    expect(composant).toContain('losange')
    // Le libellé est toujours rendu, visible ou réservé aux lecteurs d'écran.
    expect(composant).toContain('lecteur-seul')
  })
})

describe('les contrastes écrits en commentaire dans tokens.css', () => {
  it('correspondent au calcul, à 0,05 près', () => {
    // Format attendu : `--token: #abcdef;   /* 12,34 / 11,22 */`
    const lignes = [
      ...CSS.matchAll(
        /--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});\s*\/\*\s*([\d,]+)\s*\/\s*([\d,]+)\s*\*\//g,
      ),
    ]
    expect(lignes.length, 'aucun contraste documenté trouvé').toBeGreaterThan(8)

    for (const [, nom, hex, surFond, surSurface] of lignes) {
      // Les commentaires du bloc sombre se rapportent aux fonds sombres.
      const sombre = Object.hasOwn(SOMBRE, nom!) && SOMBRE[nom!] === hex!.toLowerCase()
      const tokens = sombre && CLAIR[nom!] !== hex!.toLowerCase() ? SOMBRE : CLAIR
      const attenduFond = Number(surFond!.replace(',', '.'))
      const attenduSurface = Number(surSurface!.replace(',', '.'))
      expect(contraste(hex!, tokens.fond!), `--${nom} sur --fond`).toBeCloseTo(attenduFond, 1)
      expect(contraste(hex!, tokens.surface!), `--${nom} sur --surface`).toBeCloseTo(
        attenduSurface,
        1,
      )
    }
  })
})
