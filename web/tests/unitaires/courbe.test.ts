/**
 * Géométrie de la courbe de prix.
 *
 * Une erreur de géométrie produit une courbe qui **a l'air** correcte : une ligne
 * plate, un pic au mauvais endroit, une série tracée à l'envers. Aucune capture
 * d'écran ne la trahit, et c'est pourquoi ces tests portent sur des valeurs dont on
 * connaît la réponse à l'avance.
 */
import { describe, expect, it } from 'vitest'
import { bornes, tracer, type PointPrix } from '../../app/composables/courbe'

function point(jour: number, prix: number): PointPrix {
  return { maj: `2026-11-${String(jour).padStart(2, '0')}T12:00:00Z`, prix_eur_l: prix }
}

describe('bornes', () => {
  it('ne part pas de zéro', () => {
    // Un axe partant de zéro écraserait une variation de 1,80 à 2,10 en ligne droite.
    const { bas, haut } = bornes([1.8, 1.95, 2.1])
    expect(bas).toBeGreaterThan(1.7)
    expect(haut).toBeLessThan(2.2)
    expect(bas).toBeLessThan(1.8)
    expect(haut).toBeGreaterThan(2.1)
  })

  it('donne une plage minimale à une série plate', () => {
    // Sans cela, la hauteur vaut zéro et le tracé divise par zéro.
    const { bas, haut } = bornes([1.879, 1.879, 1.879])
    expect(haut - bas).toBeCloseTo(0.02, 6)
    expect((bas + haut) / 2).toBeCloseTo(1.879, 6)
  })

  it('survit à une série vide', () => {
    expect(bornes([])).toEqual({ bas: 0, haut: 1 })
  })
})

describe('tracer', () => {
  it('rend un tracé vide pour aucun point', () => {
    const tracee = tracer([], 300, 100)
    expect(tracee.chemin).toBe('')
    expect(tracee.points).toHaveLength(0)
  })

  it('pose un point unique à droite, là où se trouve le prix courant', () => {
    // À gauche, il laisserait croire à un prix ancien suivi d'un trou.
    const tracee = tracer([point(28, 1.879)], 300, 100)
    expect(tracee.points).toHaveLength(1)
    expect(tracee.points[0]!.x).toBe(300)
  })

  it('place le plus bas en bas et le plus haut en haut', () => {
    // En SVG, y croît vers le bas : un prix élevé doit avoir un y PETIT. C'est
    // exactement l'inversion qu'on oublie, et qui dessine la courbe à l'envers.
    const tracee = tracer([point(1, 1.8), point(15, 2.1)], 300, 100)
    const [premier, second] = tracee.points
    expect(second!.y).toBeLessThan(premier!.y)
  })

  it('trace un escalier, pas une diagonale', () => {
    // Un prix ne glisse pas d'une valeur à l'autre : il change d'un coup et reste.
    // Une courbe lissée inventerait des prix qui n'ont jamais été affichés.
    const tracee = tracer([point(1, 1.8), point(15, 2.0)], 300, 100)
    expect(tracee.chemin).toContain('H ')
    expect(tracee.chemin).toContain('V ')
    expect(tracee.chemin).not.toContain('C ')
    expect(tracee.chemin).not.toContain('L ')
  })

  it('prolonge le dernier prix jusqu a maintenant', () => {
    // Le dernier prix connu est encore en vigueur aujourd'hui, et le segment plat de
    // droite montre depuis combien de temps. Sans `jusquA`, l'axe s'arrete au dernier
    // changement et la courbe semble s'interrompre.
    const maintenant = Date.parse('2026-11-29T12:00:00Z')
    const tracee = tracer([point(1, 1.8), point(15, 2.0)], 300, 100, { jusquA: maintenant })
    expect(tracee.chemin.trimEnd().endsWith('H 300')).toBe(true)
    // Le dernier changement est au 15 sur une plage du 1er au 29 : il tombe donc vers
    // la moitie de la largeur, et le plat occupe l'autre moitie.
    expect(tracee.points[1]!.x).toBeGreaterThan(120)
    expect(tracee.points[1]!.x).toBeLessThan(180)
  })

  it('ignore un `jusquA` anterieur au dernier changement', () => {
    // Une horloge en retard ou un fuseau mal lu ne doit pas replier la courbe sur
    // elle-meme : on ne recule jamais la borne droite.
    const tracee = tracer([point(1, 1.8), point(20, 2.0)], 300, 100, {
      jusquA: Date.parse('2026-11-10T12:00:00Z'),
    })
    expect(tracee.points[1]!.x).toBe(300)
  })

  it('refermé, l aplat revient au premier point', () => {
    const tracee = tracer([point(1, 1.8), point(15, 2.0)], 300, 100)
    expect(tracee.aplat.endsWith('Z')).toBe(true)
    expect(tracee.aplat).toContain('V 100')
  })

  it('respecte l échelle du temps, pas le rang des points', () => {
    // Trois changements dont deux rapprochés : le point du milieu doit être près du
    // début, pas au milieu de la largeur. Un tracé indexé sur le rang mentirait sur
    // le rythme des changements.
    const tracee = tracer([point(1, 1.8), point(3, 1.85), point(29, 1.9)], 280, 100)
    const milieu = tracee.points[1]!.x
    expect(milieu).toBeLessThan(40)
  })

  it('garde une série plate au milieu de la hauteur', () => {
    const tracee = tracer([point(1, 1.879), point(20, 1.879)], 300, 100)
    for (const place of tracee.points) {
      expect(place.y).toBeCloseTo(50, 5)
    }
  })
})
