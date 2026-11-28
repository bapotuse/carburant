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

/** Les six codes de carburant du flux officiel. */
export type CodeCarburant = 'gazole' | 'sp95' | 'e10' | 'sp98' | 'e85' | 'gplc'

/**
 * Le nom lisible d'un carburant.
 *
 * `sp95` et `e10` sont des codes d'API : ils n'ont rien à faire à l'écran. Cette table
 * est la seule du front, et `PastilleCarburant` la lit aussi — deux tables auraient
 * fini par diverger, et c'est exactement ce qui est arrivé avant ce correctif : la
 * fiche station affichait « e10 » dans ses onglets.
 */
export const LIBELLES_CARBURANT: Record<CodeCarburant, string> = {
  gazole: 'Gazole',
  sp95: 'SP95',
  e10: 'SP95-E10',
  sp98: 'SP98',
  e85: 'E85',
  gplc: 'GPLc',
}

/** Le nom lisible d'un code, ou le code lui-même s'il est inconnu. */
export function libelleCarburant(code: string): string {
  return LIBELLES_CARBURANT[code as CodeCarburant] ?? code
}

/**
 * Les types de voie, qui restent en minuscules : « 32 boulevard Schloesing ».
 *
 * C'est la typographie française des adresses, et elle n'est pas facultative — « 32
 * Boulevard Schloesing » est de l'anglais déguisé.
 */
const TYPES_DE_VOIE = new Set([
  'rue',
  'avenue',
  'boulevard',
  'bd',
  'place',
  'chemin',
  'route',
  'impasse',
  'allee',
  'allée',
  'allees',
  'allées',
  'quai',
  'cours',
  'square',
  'voie',
  'passage',
  'sentier',
  'esplanade',
  'rond-point',
  'autoroute',
  'aire',
  'zone',
  'lieu-dit',
  'faubourg',
  'traverse',
  'montee',
  'montée',
  'descente',
  'promenade',
  'parvis',
])

/** Les particules, qui restent en minuscules même au milieu d'un nom propre. */
const PARTICULES = new Set([
  'de',
  'du',
  'des',
  'la',
  'le',
  'les',
  'et',
  'a',
  'à',
  'au',
  'aux',
  'sur',
  'sous',
  'en',
  'lès',
  'les-',
  'd',
  'l',
])

/**
 * Les sigles qu'on laisse en capitales, et la liste est volontairement **fermée**.
 *
 * Une heuristique de longueur ne peut pas marcher : « ZA » et « MER » font tous deux
 * trois lettres ou moins et tous deux en capitales dans le flux. Un mot contenant un
 * chiffre est en revanche toujours un sigle ou un numéro de route : « RN7 », « D921 ».
 */
const SIGLES = new Set([
  'ZA',
  'ZAC',
  'ZAE',
  'ZI',
  'ZE',
  'CC',
  'CCAL',
  'CD',
  'RN',
  'RD',
  'DN',
  'BP',
  'PK',
  'EDF',
  'SNCF',
  'CE',
  'LD',
])

/**
 * Une adresse du flux officiel, rendue lisible.
 *
 * Le flux publie les adresses **en capitales** : « 32 BOULEVARD SCHLOESING ». Les
 * laisser telles quelles donne un titre qui crie, et les capitales se lisent plus
 * lentement — ce qui compte pour quelqu'un qui cherche une station au volant.
 *
 * La règle appliquée est celle du français : le type de voie en minuscules, le nom
 * propre capitalisé. Les sigles connus et les mots contenant un chiffre sont
 * **préservés** — « ZA », « RN7 », « CC » survivent, « RUE » et « MER » non.
 *
 * On ne touche pas à la donnée : c'est une transformation d'affichage, et l'adresse
 * d'origine reste celle de l'API.
 *
 * @example adresseLisible('32 BOULEVARD SCHLOESING') // '32 boulevard Schloesing'
 */
export function adresseLisible(adresse: string): string {
  const mots = adresse.trim().split(/(\s+)/)
  let premierMot = true
  return mots
    .map((mot) => {
      if (/^\s+$/.test(mot) || mot === '') return mot
      const nu = mot.replace(/[^\p{L}\p{N}-]/gu, '')
      const minuscule = mot.toLocaleLowerCase('fr-FR')
      const sansPonctuation = nu.toLocaleLowerCase('fr-FR')

      // Un sigle, reconnu par une **liste explicite** et non par une heuristique de
      // longueur. « MER » et « ZA » font tous deux trois lettres ou moins et tous
      // deux en capitales : seule une liste les distingue. Premiere version faite
      // sur la longueur, corrigee par un test -- elle rendait « route de la MER ».
      const sigle =
        nu === nu.toLocaleUpperCase('fr-FR') &&
        /\p{L}/u.test(nu) &&
        (SIGLES.has(nu) || /\d/.test(nu))
      if (sigle) {
        premierMot = false
        return mot
      }

      if (TYPES_DE_VOIE.has(sansPonctuation) || (!premierMot && PARTICULES.has(sansPonctuation))) {
        premierMot = false
        return minuscule
      }
      premierMot = false
      // Capitalise aussi après un tiret ou une apostrophe : « SAINT-JEAN » devient
      // « Saint-Jean », « L'ILE-ROUSSE » devient « L'Ile-Rousse ».
      return minuscule.replace(/(^|[-'’])(\p{L})/gu, (_, avant: string, lettre: string) => {
        return avant + lettre.toLocaleUpperCase('fr-FR')
      })
    })
    .join('')
}
