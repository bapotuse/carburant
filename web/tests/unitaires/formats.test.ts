import { describe, expect, it } from 'vitest'
import {
  INSECABLE_ETROITE as FINE,
  ageRelatif,
  co2Kg,
  dateCourte,
  dateEtHeure,
  distanceKm,
  entier,
  euros,
  litres,
  prixLitre,
} from '../../app/composables/formats'

/**
 * `Intl` seul ne donne pas une typographie française correcte : ces tests verrouillent
 * les normalisations, caractère par caractère. Ils doivent rester identiques aux tests
 * des helpers Python du serveur MCP (mcp/tests/test_formats.py).
 */

const REF = new Date('2026-11-23T16:00:00Z') // 17 h 00 à Paris en novembre

describe('prix', () => {
  it("affiche trois décimales, c'est l'exemple de CLAUDE.md", () => {
    expect(prixLitre(1.879)).toBe(`1,879${FINE}€/L`)
  })

  it('garde ses trois décimales même sur un prix rond', () => {
    expect(prixLitre(1.9)).toBe(`1,900${FINE}€/L`)
  })

  it("n'utilise jamais l'espace insécable large que met Intl devant l'euro", () => {
    expect(prixLitre(1.879)).not.toContain(' ')
    expect(euros(93.95)).not.toContain(' ')
  })
})

describe('montants et volumes', () => {
  it('formate les euros', () => {
    expect(euros(93.95)).toBe(`93,95${FINE}€`)
  })

  it('écrit le litre en L majuscule, pas en l minuscule comme Intl', () => {
    expect(litres(50)).toBe(`50${FINE}L`)
    expect(litres(42.5)).toBe(`42,5${FINE}L`)
  })

  it('groupe les milliers avec une espace fine insécable', () => {
    expect(entier(9826)).toBe(`9${FINE}826`)
  })
})

describe('distances', () => {
  it.each([
    [0.35, `350${FINE}m`],
    [0.999, `999${FINE}m`],
    [1, `1,0${FINE}km`],
    [2.4, `2,4${FINE}km`],
    [12.7, `13${FINE}km`],
  ])('formate %s km', (km, attendu) => {
    expect(distanceKm(km)).toBe(attendu)
  })
})

describe('CO2', () => {
  it('formate une masse', () => {
    expect(co2Kg(155)).toBe(`155${FINE}kg${FINE}CO2e`)
    expect(co2Kg(3.1)).toBe(`3,1${FINE}kg${FINE}CO2e`)
  })
})

describe('dates', () => {
  it("rend l'exemple de CLAUDE.md, avec une espace insécable", () => {
    expect(dateCourte(REF)).toBe(`23${FINE}nov.`)
  })

  it("écrit l'heure à la française, pas 17:00", () => {
    expect(dateEtHeure(REF)).toBe(`23${FINE}nov. à 17${FINE}h${FINE}00`)
  })

  it('bascule bien en heure de Paris', () => {
    // Le 31 décembre à 23 h 30 UTC, il est déjà le 1er janvier à Paris.
    expect(dateCourte(new Date('2025-12-31T23:30:00Z'))).toBe(`1${FINE}janv.`)
  })

  it("décale de deux heures en été, pas d'une", () => {
    expect(dateEtHeure(new Date('2026-07-15T12:30:00Z'))).toContain(`14${FINE}h${FINE}30`)
  })
})

describe('âge relatif', () => {
  const ilYA = (ms: number) => ageRelatif(new Date(REF.getTime() - ms), REF)

  it.each([
    [20_000, "à l'instant"],
    [7 * 60_000, 'il y a 7 minutes'],
    [5 * 3_600_000, 'il y a 5 heures'],
    [24 * 3_600_000, 'hier'],
    [3 * 24 * 3_600_000, 'il y a 3 jours'],
    [45 * 24 * 3_600_000, 'le mois dernier'],
  ])("dit %s ms comme à l'oral", (ms, attendu) => {
    expect(ilYA(ms)).toBe(attendu)
  })

  it('ne devient pas absurde pour une date dans le futur', () => {
    // 181 dates du flux étaient dans le futur quand on les lisait en UTC.
    expect(ageRelatif(new Date(REF.getTime() + 50 * 60_000), REF)).toBe("à l'instant")
  })
})

describe('aucun format ne laisse passer une espace ordinaire avant son unité', () => {
  it.each([prixLitre(1.879), euros(10), litres(50), distanceKm(2.4), co2Kg(155), entier(9826)])(
    '%s',
    (rendu) => {
      expect(rendu).not.toMatch(/\d /)
      expect(rendu).toContain(FINE)
    },
  )
})
