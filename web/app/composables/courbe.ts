/**
 * Géométrie d'une courbe de prix, en fonctions pures.
 *
 * Séparée du composant pour une raison précise : une erreur de géométrie produit une
 * courbe qui **a l'air** correcte — une ligne plate, un pic au mauvais endroit — et
 * aucune capture d'écran ne la trahit. En fonctions pures, elle se teste sur des
 * valeurs dont on connaît la réponse.
 *
 * Pas de librairie de graphiques : une courbe à une série, c'est une chaîne de
 * caractères. Le budget JS de l'accueil est de 100 Ko gzip, et une librairie en
 * coûterait la moitié pour ce seul usage.
 */

/** Un point de la courbe : un instant et un prix. */
export interface PointPrix {
  /** Horodatage ISO-8601. */
  readonly maj: string
  readonly prix_eur_l: number
}

export interface Bornes {
  readonly bas: number
  readonly haut: number
}

export interface Tracee {
  /** L'attribut `d` du chemin SVG, dans le repère 0..largeur × 0..hauteur. */
  readonly chemin: string
  /** Le même tracé, refermé vers le bas : pour l'aplat sous la courbe. */
  readonly aplat: string
  readonly bornes: Bornes
  /** Les points, avec leurs coordonnées à l'écran, pour les repères et le survol. */
  readonly points: readonly { x: number; y: number; point: PointPrix }[]
}

/**
 * Les bornes verticales, avec une marge.
 *
 * **On ne part pas de zéro**, et c'est volontaire : sur une plage de prix de 1,80 à
 * 2,10 EUR, un axe partant de zéro écrase toute la variation en une ligne droite.
 * L'axe est donc annoté avec ses deux valeurs, pour qu'il ne puisse pas tromper.
 *
 * Une série parfaitement plate obtiendrait une hauteur nulle, donc une division par
 * zéro : on lui donne alors une plage minimale et la courbe se dessine au milieu,
 * ce qui est la lecture juste — ce prix n'a pas bougé.
 */
export function bornes(prix: readonly number[], plageMinimale = 0.02): Bornes {
  if (prix.length === 0) return { bas: 0, haut: 1 }
  const bas = Math.min(...prix)
  const haut = Math.max(...prix)
  const etendue = haut - bas
  if (etendue < plageMinimale) {
    const centre = (haut + bas) / 2
    return { bas: centre - plageMinimale / 2, haut: centre + plageMinimale / 2 }
  }
  const marge = etendue * 0.12
  return { bas: bas - marge, haut: haut + marge }
}

/**
 * Transforme des points en tracé SVG.
 *
 * Les points sont attendus **du plus ancien au plus récent** : c'est l'inverse de ce
 * que rend l'API, qui les donne du plus récent au plus ancien. L'appelant inverse ;
 * cette fonction ne devine pas l'ordre, parce qu'une courbe tracée à l'envers est
 * exactement le genre d'erreur qui ne se voit pas.
 *
 * Le tracé est **en escalier** et non lissé, parce que c'est ce que la donnée dit : un
 * prix ne glisse pas d'une valeur à l'autre, il change d'un coup et reste. Une courbe
 * lissée inventerait des prix intermédiaires qui n'ont jamais été affichés.
 */
export function tracer(
  points: readonly PointPrix[],
  largeur: number,
  hauteur: number,
  options: { plageMinimale?: number; jusquA?: number } = {},
): Tracee {
  const limites = bornes(
    points.map((p) => p.prix_eur_l),
    options.plageMinimale,
  )
  if (points.length === 0) {
    return { chemin: '', aplat: '', bornes: limites, points: [] }
  }

  const premier = Date.parse(points[0]!.maj)
  // L'axe va du premier changement **jusqu'a maintenant**, et non jusqu'au dernier
  // changement. La difference est tout l'interet de la courbe : le segment plat de
  // droite montre depuis combien de temps le prix actuel n'a pas bouge. Un axe
  // s'arretant au dernier changement laisserait croire que la serie s'arrete la.
  const dernier = Math.max(
    options.jusquA ?? Date.parse(points[points.length - 1]!.maj),
    Date.parse(points[points.length - 1]!.maj),
  )
  const duree = dernier - premier
  const amplitude = limites.haut - limites.bas

  const places = points.map((point) => {
    // Une série d'un seul point, ou tous au même instant : on le pose à droite, là où
    // se trouve le prix courant. Le poser à gauche laisserait croire à un prix ancien.
    const x = duree > 0 ? ((Date.parse(point.maj) - premier) / duree) * largeur : largeur
    const y = hauteur - ((point.prix_eur_l - limites.bas) / amplitude) * hauteur
    return { x, y, point }
  })

  const morceaux: string[] = [`M ${arrondi(places[0]!.x)} ${arrondi(places[0]!.y)}`]
  for (let i = 1; i < places.length; i += 1) {
    const precedent = places[i - 1]!
    const actuel = places[i]!
    // L'escalier : on avance à l'horizontale au prix précédent, puis on saute.
    morceaux.push(`H ${arrondi(actuel.x)}`)
    if (actuel.y !== precedent.y) morceaux.push(`V ${arrondi(actuel.y)}`)
  }
  // Le dernier prix court jusqu'au bord droit : il est encore en vigueur aujourd'hui.
  const bordDroit = arrondi(largeur)
  if (places[places.length - 1]!.x < largeur) morceaux.push(`H ${bordDroit}`)

  const chemin = morceaux.join(' ')
  const aplat = `${chemin} V ${arrondi(hauteur)} H ${arrondi(places[0]!.x)} Z`
  return { chemin, aplat, bornes: limites, points: places }
}

/** Deux décimales suffisent dans un repère de quelques centaines d'unités. */
function arrondi(valeur: number): number {
  return Math.round(valeur * 100) / 100
}
