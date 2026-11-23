/**
 * Formats français, construits sur `Intl` en `fr-FR` puis normalisés.
 *
 * `Intl` seul ne donne pas une typographie française correcte. Mesuré sur ICU 78 :
 *
 * | Appel                                | Ce que rend `Intl`      | Ce qu'il faut            |
 * |--------------------------------------|-------------------------|--------------------------|
 * | `style: 'currency'`                  | `93,95` U+00A0 `EUR`    | `93,95` U+202F `EUR`     |
 * | `style: 'unit', unit: 'kilometer'`   | `2,4` U+202F `km`       | correct                  |
 * | `style: 'unit', unit: 'liter'`       | `50` U+202F `l`         | `50` U+202F `L`          |
 * | `day: 'numeric', month: 'short'`     | `23` espace `nov.`      | `23` U+202F `nov.`       |
 * | `hour: 'numeric', minute: '2-digit'` | `17:00`                 | `17` U+202F `h` U+202F `00` |
 *
 * Autrement dit, `Intl` emploie U+00A0 (espace insécable) devant l'euro mais U+202F
 * (espace fine insécable) devant les unités. L'usage français, lui, veut U+202F dans
 * les deux cas. Le litre s'abrège « L » majuscule, pour ne pas confondre avec le
 * chiffre 1. Et l'heure française s'écrit « 17 h 00 », pas « 17:00 ».
 *
 * Ces règles sont donc appliquées ici, une fois, et testées
 * (tests/unitaires/formats.test.ts). Les helpers Python du serveur MCP suivent
 * exactement les mêmes règles.
 */

/** Espace fine insécable : le séparateur typographique français. */
export const INSECABLE_ETROITE = '\u202F'

const INSECABLE = '\u00A0'

/** Remplace toute espace insécable large par une fine, pour n'en avoir qu'une seule. */
function normaliserEspaces(texte: string): string {
  return texte.replaceAll(INSECABLE, INSECABLE_ETROITE)
}

const nombreFr = (options: Intl.NumberFormatOptions) => new Intl.NumberFormat('fr-FR', options)

/**
 * Un prix au litre, tel qu'il s'affiche en station : trois décimales.
 * @example prixLitre(1.879) // '1,879 €/L' (espaces fines insécables)
 */
export function prixLitre(prixEurL: number): string {
  const valeur = nombreFr({
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  }).format(prixEurL)
  return `${normaliserEspaces(valeur)}${INSECABLE_ETROITE}€/L`
}

/** Un montant en euros, deux décimales. */
export function euros(montant: number): string {
  return normaliserEspaces(nombreFr({ style: 'currency', currency: 'EUR' }).format(montant))
}

/** Un volume en litres. « L » majuscule, jamais « l ». */
export function litres(volume: number): string {
  const valeur = nombreFr({
    maximumFractionDigits: Number.isInteger(volume) ? 0 : 1,
  }).format(volume)
  return `${normaliserEspaces(valeur)}${INSECABLE_ETROITE}L`
}

/** Une distance. En dessous du kilomètre, on parle en mètres. */
export function distanceKm(km: number): string {
  if (km < 1) {
    const metres = nombreFr({ maximumFractionDigits: 0 }).format(Math.round(km * 1000))
    return `${normaliserEspaces(metres)}${INSECABLE_ETROITE}m`
  }
  const valeur = nombreFr({
    minimumFractionDigits: km >= 10 ? 0 : 1,
    maximumFractionDigits: km >= 10 ? 0 : 1,
  }).format(km)
  return `${normaliserEspaces(valeur)}${INSECABLE_ETROITE}km`
}

/** Une masse de CO2 équivalent. */
export function co2Kg(kg: number): string {
  const valeur = nombreFr({
    minimumFractionDigits: kg >= 10 ? 0 : 1,
    maximumFractionDigits: kg >= 10 ? 0 : 1,
  }).format(kg)
  return `${normaliserEspaces(valeur)}${INSECABLE_ETROITE}kg${INSECABLE_ETROITE}CO2e`
}

/** Un entier, milliers groupés. */
export function entier(valeur: number): string {
  return normaliserEspaces(nombreFr({ maximumFractionDigits: 0 }).format(valeur))
}

/** Une date courte, en heure de Paris. @example '23 nov.' */
export function dateCourte(instant: Date): string {
  const texte = new Intl.DateTimeFormat('fr-FR', {
    day: 'numeric',
    month: 'short',
    timeZone: 'Europe/Paris',
  }).format(instant)
  // `Intl` met une espace ordinaire entre le jour et le mois : on la rend insécable.
  return normaliserEspaces(texte).replace(' ', INSECABLE_ETROITE)
}

/** Date et heure, en heure de Paris. @example '23 nov. à 17 h 00' */
export function dateEtHeure(instant: Date): string {
  const heures = new Intl.DateTimeFormat('fr-FR', {
    hour: 'numeric',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: 'Europe/Paris',
  }).format(instant)
  // « 17:00 » n'est pas une heure française : on écrit « 17 h 00 ».
  const [h, m] = heures.split(':')
  return `${dateCourte(instant)} à ${Number(h)}${INSECABLE_ETROITE}h${INSECABLE_ETROITE}${m}`
}

/**
 * L'âge d'un prix, dit comme à l'oral : « il y a 7 minutes », « hier ».
 *
 * C'est la formulation utilisée à côté de chaque prix. Elle évite de laisser croire à
 * une fraîcheur qui n'existe pas, là où une date brute passe inaperçue.
 */
export function ageRelatif(instant: Date, reference: Date = new Date()): string {
  const secondes = (reference.getTime() - instant.getTime()) / 1000
  if (secondes < 60) return "à l'instant"
  const relatif = new Intl.RelativeTimeFormat('fr-FR', { numeric: 'auto' })
  const minutes = Math.floor(secondes / 60)
  if (minutes < 60) return relatif.format(-minutes, 'minute')
  const heures = Math.floor(minutes / 60)
  if (heures < 24) return relatif.format(-heures, 'hour')
  const jours = Math.floor(heures / 24)
  if (jours < 31) return relatif.format(-jours, 'day')
  return relatif.format(-Math.floor(jours / 30), 'month')
}
