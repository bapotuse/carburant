/**
 * Client de l'API, type depuis l'OpenAPI.
 *
 * Les types viennent de `app/api/genere/schema.d.ts`, **genere** par
 * `pnpm generer-client` depuis `openapi.json`. On n'en écrit aucun à la main : si une
 * route change et que le client n'est pas régénéré, la CI échoue. Le contrat ne peut
 * donc pas diverger du code.
 *
 * Les erreurs de l'API sont au format `application/problem+json`. Leur champ `detail`
 * est rédigé pour être affiché tel quel : on ne le reformule pas.
 */
import type { paths } from '../api/genere/schema'

type Chemins = paths

export type StationsProches =
  Chemins['/v1/stations/proches']['get']['responses']['200']['content']['application/json']
export type Station = StationsProches['stations'][number]
export type PrixCarburant = Station['prix'][number]
export type Fraicheur = NonNullable<PrixCarburant['fraicheur']>

export type Geocodage =
  Chemins['/v1/geocode']['get']['responses']['200']['content']['application/json']
export type Candidat = Geocodage['candidats'][number]

export type Meta = Chemins['/v1/meta']['get']['responses']['200']['content']['application/json']

/** Une erreur renvoyée par l'API, au format problem+json. */
export class ErreurAPI extends Error {
  readonly statut: number
  readonly titre: string

  constructor(statut: number, titre: string, detail: string) {
    super(detail)
    this.name = 'ErreurAPI'
    this.statut = statut
    this.titre = titre
  }
}

/** Erreur réseau : l'API n'a pas répondu du tout. */
export class ErreurReseau extends Error {
  constructor() {
    super('Le service ne répond pas. Vérifiez votre connexion, puis réessayez.')
    this.name = 'ErreurReseau'
  }
}

/**
 * L'adresse de l'API, qui n'est pas la même selon qui appelle.
 *
 * Le navigateur passe par l'adresse publique ; le rendu serveur, lui, tourne dans le
 * conteneur web et joint l'API par son nom de service sur le réseau Docker. Utiliser
 * la même des deux côtés marche en développement et casse en production.
 */
export function baseApi(): string {
  const config = useRuntimeConfig()
  return import.meta.server ? config.apiBaseInterne : config.public.apiBase
}

async function appeler<T>(chemin: string, parametres: Record<string, string>): Promise<T> {
  const base = baseApi()
  const url = `${base}${chemin}?${new URLSearchParams(parametres)}`

  let reponse: Response
  try {
    reponse = await fetch(url, { headers: { Accept: 'application/json' } })
  } catch {
    throw new ErreurReseau()
  }

  if (!reponse.ok) {
    // L'API répond en problem+json ; un intermédiaire (proxy, erreur 502) peut
    // renvoyer autre chose. On ne suppose jamais la forme du corps.
    let titre = 'Erreur'
    let detail = `Le service a répondu ${reponse.status}.`
    try {
      const probleme = await reponse.json()
      titre = probleme.title ?? titre
      detail = probleme.detail ?? detail
    } catch {
      /* corps illisible : on garde le message par défaut */
    }
    throw new ErreurAPI(reponse.status, titre, detail)
  }

  return (await reponse.json()) as T
}

/** Les stations autour d'un point, triées par prix. */
export function stationsProches(options: {
  lat: number
  lon: number
  carburant?: string
  rayonKm?: number
  tri?: 'prix' | 'distance'
  limite?: number
}): Promise<StationsProches> {
  const parametres: Record<string, string> = {
    lat: String(options.lat),
    lon: String(options.lon),
    rayon_km: String(options.rayonKm ?? 10),
    tri: options.tri ?? 'prix',
    limite: String(options.limite ?? 20),
  }
  if (options.carburant) parametres.carburant = options.carburant
  return appeler<StationsProches>('/v1/stations/proches', parametres)
}

/** Géocode un texte libre. Lire `ambigu` avant d'utiliser le premier candidat. */
export function geocoder(q: string, limite = 5): Promise<Geocodage> {
  return appeler<Geocodage>('/v1/geocode', { q, limite: String(limite) })
}

/** L'état des données servies : dernière collecte, volumes, couverture. */
export function meta(): Promise<Meta> {
  return appeler<Meta>('/v1/meta', {})
}
