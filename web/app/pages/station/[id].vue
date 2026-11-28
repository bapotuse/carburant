<script setup lang="ts">
/**
 * La fiche d'une station. **Elle ne cache rien.**
 *
 * C'est sa raison d'être, et ce qui la distingue d'une recherche. Une recherche écarte
 * les prix périmés et les carburants en rupture, parce qu'elle répond à « où aller
 * maintenant ». Une fiche, elle, répond à « qu'est-ce qu'on sait de cette station » :
 * un prix de deux mois y figure, daté et marqué comme périmé, et un carburant annoncé
 * sans prix est dit en rupture. Masquer l'un ou l'autre laisserait croire que la
 * station ne vend pas ce carburant.
 *
 * Le flux officiel ne publie **ni nom ni enseigne**. L'enseigne vient d'OpenStreetMap,
 * qui en couvre 99,4 % ; quand elle manque, l'adresse fait l'identité, et la page ne
 * fabrique pas un nom pour combler le vide.
 */
import { ErreurAPI, historique, station, type PrixFiche } from '../../composables/api'
import { adresseLisible, dateEtHeure, libelleCarburant } from '../../composables/formats'

const route = useRoute()
const identifiant = computed(() => Number(route.params.id))

if (!Number.isInteger(identifiant.value) || identifiant.value <= 0) {
  throw createError({ statusCode: 404, statusMessage: 'Station introuvable', fatal: true })
}

/**
 * La fiche et l'historique sont demandés **en parallèle** : ils ne s'attendent pas, et
 * le rendu serveur paie le plus lent des deux et non leur somme.
 *
 * La conversion de l'erreur se fait **dans** le gestionnaire, pas après. `useAsyncData`
 * enveloppe ce qui est levé dans une erreur Nuxt : un `instanceof ErreurAPI` testé à
 * l'extérieur est donc toujours faux, et une station inconnue répondait 502 au lieu de
 * 404. Constaté en appelant `/station/99999999`, pas en relisant le code.
 */
const { data, error } = await useAsyncData(`station-${identifiant.value}`, async () => {
  try {
    const [fiche, serie] = await Promise.all([
      station(identifiant.value),
      historique(identifiant.value, { jours: 365, limite: 500 }),
    ])
    return { fiche, serie }
  } catch (erreur) {
    if (erreur instanceof ErreurAPI && erreur.statut === 404) {
      throw createError({ statusCode: 404, statusMessage: 'Station introuvable', fatal: true })
    }
    throw createError({
      statusCode: 502,
      statusMessage: 'Le service ne répond pas',
      fatal: true,
    })
  }
})

if (error.value) throw error.value

const fiche = computed(() => data.value!.fiche)

/** L'enseigne si OpenStreetMap la connaît, sinon l'adresse. Jamais un nom inventé. */
const nom = computed(
  () =>
    fiche.value.enseigne?.nom ??
    (fiche.value.adresse ? adresseLisible(fiche.value.adresse) : `Station ${fiche.value.id}`),
)
const lieu = computed(() => {
  const adresse = fiche.value.adresse ? adresseLisible(fiche.value.adresse) : null
  const commune = [fiche.value.cp, fiche.value.ville].filter(Boolean).join(' ')
  // Sans enseigne, l'adresse est deja le titre : la repeter juste en dessous ne dit
  // rien de plus.
  const morceaux = fiche.value.enseigne ? [adresse, commune] : [commune]
  return morceaux.filter(Boolean).join(', ')
})

useHead({
  title: `${nom.value} — prix des carburants`,
})

/** Les prix vendus, prix d'abord, ruptures ensuite : on lit ce qui est disponible. */
/**
 * L'ordre d'affichage des carburants, celui des étiquettes européennes et du flux.
 *
 * L'API rend les prix dans l'ordre alphabétique de leur code : « e10, e85, gazole ».
 * Le gazole représente 97 % des stations et c'est le premier que l'œil cherche ; le
 * laisser en troisième position parce que « g » vient après « e » est un classement
 * par accident.
 */
const ORDRE = ['gazole', 'sp95', 'e10', 'sp98', 'e85', 'gplc']

const tousLesPrix = computed<PrixFiche[]>(() =>
  [...(fiche.value.prix ?? [])].sort(
    (a, b) => ORDRE.indexOf(a.carburant) - ORDRE.indexOf(b.carburant),
  ),
)
const prixVendus = computed(() =>
  tousLesPrix.value.filter((p) => p.prix_eur_l != null && !p.rupture),
)
const ruptures = computed(() => tousLesPrix.value.filter((p) => p.rupture != null))

/** Le carburant dont on montre l'historique. Le premier prix connu par défaut. */
const carburantSuivi = ref<string | null>(null)
const carburantCourbe = computed(
  () => carburantSuivi.value ?? prixVendus.value[0]?.carburant ?? null,
)

/**
 * L'historique du carburant suivi, **du plus ancien au plus récent**.
 *
 * L'API rend les changements du plus récent au plus ancien, ce qui est le bon ordre
 * pour une liste et l'inverse du bon ordre pour une courbe. On inverse ici, une fois,
 * plutôt que de laisser la fonction de tracé deviner : une courbe tracée à l'envers
 * est exactement le genre d'erreur qui ne se voit pas.
 */
const serieCourbe = computed(() => {
  const code = carburantCourbe.value
  if (!code) return []
  const changements = data.value?.serie.changements ?? []
  return changements
    .filter((c) => c.carburant === code)
    .map((c) => ({ maj: c.maj, prix_eur_l: c.prix_eur_l }))
    .reverse()
})

const horaires = computed(() => (fiche.value.horaires ?? null) as HorairesStation | null)

/**
 * Une station sans aucune plage d'ouverture publiée.
 *
 * Le cas est fréquent et la première version l'affichait très mal : un bandeau
 * « Automate accessible 24 h/24 » suivi de sept lignes « fermé ». Les deux sont vrais
 * — l'automate fonctionne, personne n'accueille — mais côte à côte ils se
 * contredisent à la lecture. Constaté sur la capture, pas dans le code.
 */
const sansAccueil = computed(() => {
  const h = horaires.value
  if (!h) return false
  return h.jours.every((jour) => jour.ferme || jour.plages.length === 0)
})
const services = computed(() => fiche.value.services ?? [])

interface JourHoraire {
  readonly nom: string
  readonly jour: number
  readonly ferme: boolean
  readonly plages: readonly (readonly [string, string])[]
}
interface HorairesStation {
  readonly jours: readonly JourHoraire[]
  readonly automate_24_24: boolean
}

/** Le jour de la semaine à Paris, en norme ISO : 1 lundi, 7 dimanche. */
function jourIsoAParis(): number {
  const nom = new Intl.DateTimeFormat('en-GB', {
    weekday: 'short',
    timeZone: 'Europe/Paris',
  }).format(new Date())
  return { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 }[nom] ?? 1
}

/**
 * Ouvert en ce moment ?
 *
 * Trois réponses, et la troisième compte autant que les deux autres : `null` veut dire
 * « on ne sait pas », parce que le flux ne publie pas les horaires de toutes les
 * stations. Afficher « fermé » faute d'horaires serait un mensonge.
 *
 * Calculé après le montage seulement : une heure rendue côté serveur serait fausse
 * dans la seconde, et le cache la servirait à tout le monde.
 */
const ouvertMaintenant = ref<boolean | null>(null)
onMounted(() => {
  const h = horaires.value
  if (!h || h.jours.length === 0) return
  if (h.automate_24_24) {
    ouvertMaintenant.value = true
    return
  }
  const aujourdhui = h.jours.find((j) => j.jour === jourIsoAParis())
  if (!aujourdhui) return
  if (aujourdhui.ferme || aujourdhui.plages.length === 0) {
    ouvertMaintenant.value = false
    return
  }
  const maintenant = new Intl.DateTimeFormat('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: 'Europe/Paris',
  }).format(new Date())
  ouvertMaintenant.value = aujourdhui.plages.some(([debut, fin]) => {
    // Une plage qui finit avant de commencer franchit minuit (« 22:00 → 06:00 ».)
    return fin > debut
      ? maintenant >= debut && maintenant < fin
      : maintenant >= debut || maintenant < fin
  })
})
</script>

<template>
  <article class="fiche">
    <header class="fiche__entete">
      <p class="fiche__fil">
        <NuxtLink to="/">Où faire le plein ?</NuxtLink>
      </p>
      <h1 class="fiche__nom">{{ nom }}</h1>
      <p v-if="lieu" class="fiche__lieu">{{ lieu }}</p>
      <p class="fiche__reperes">
        <span v-if="fiche.autoroute" class="fiche__autoroute">Sur autoroute</span>
        <span v-if="ouvertMaintenant === true" class="fiche__ouvert">Ouvert en ce moment</span>
        <span v-else-if="ouvertMaintenant === false" class="fiche__ferme">Fermé en ce moment</span>
        <!-- Pas de badge quand on ne sait pas : le flux ne publie pas les horaires de
             toutes les stations, et « fermé » par défaut serait un mensonge. -->
        <span class="fiche__pompe">nº {{ fiche.id }}</span>
      </p>
      <p v-if="!fiche.enseigne" class="fiche__sans-enseigne">
        Le flux officiel ne publie pas le nom des stations. Celle-ci n'a pas été retrouvée dans
        OpenStreetMap : elle s'identifie par son adresse.
      </p>
    </header>

    <section class="fiche__prix" aria-labelledby="titre-prix">
      <h2 id="titre-prix">Prix affichés</h2>
      <ul v-if="prixVendus.length" class="fiche__liste">
        <li v-for="p in prixVendus" :key="p.carburant" class="fiche__carburant">
          <PastilleCarburant :code="p.carburant as never" />
          <PrixTotem :prix-eur-l="p.prix_eur_l!" :taille="'l'" />
          <IndicateurFraicheur v-if="p.maj && p.fraicheur" :maj="p.maj" :fraicheur="p.fraicheur" />
        </li>
      </ul>
      <p v-else class="fiche__aucun">Aucun prix connu pour cette station.</p>

      <!-- Les ruptures sont affichées, pas filtrees : les masquer laisserait croire
           que la station ne vend pas ce carburant du tout. -->
      <p v-if="ruptures.length" class="fiche__ruptures">
        Annoncé sans prix&nbsp;:
        <span v-for="(r, i) in ruptures" :key="r.carburant">
          <template v-if="i > 0">, </template>{{ libelleCarburant(r.carburant) }}
        </span>
      </p>
    </section>

    <section v-if="carburantCourbe" class="fiche__histoire" aria-labelledby="titre-histoire">
      <h2 id="titre-histoire">Comment ce prix a bougé</h2>

      <div
        v-if="prixVendus.length > 1"
        class="fiche__choix"
        role="group"
        aria-label="Carburant suivi"
      >
        <button
          v-for="p in prixVendus"
          :key="p.carburant"
          type="button"
          class="fiche__onglet"
          :class="{ 'fiche__onglet--actif': p.carburant === carburantCourbe }"
          :aria-pressed="p.carburant === carburantCourbe"
          @click="carburantSuivi = p.carburant"
        >
          {{ libelleCarburant(p.carburant) }}
        </button>
      </div>

      <CourbePrix
        :points="serieCourbe"
        :carburant="carburantCourbe"
        :titre="`Prix du ${libelleCarburant(carburantCourbe)}`"
      />
      <!-- Inutile quand la courbe se resume deja a une phrase : « un seul prix
           connu » puis « un point par changement » se repetent. -->
      <p v-if="serieCourbe.length > 1" class="fiche__source">
        Un point par changement de prix publié, sur les douze derniers mois.
      </p>
    </section>

    <LiensItineraire :latitude="fiche.latitude" :longitude="fiche.longitude" :nom="nom" />

    <section v-if="services.length" class="fiche__services" aria-labelledby="titre-services">
      <h2 id="titre-services">Sur place</h2>
      <ul class="fiche__tags">
        <li v-for="service in services" :key="service">{{ service }}</li>
      </ul>
    </section>

    <section v-if="horaires?.jours.length" class="fiche__horaires" aria-labelledby="titre-horaires">
      <h2 id="titre-horaires">Horaires</h2>
      <p v-if="horaires.automate_24_24 && sansAccueil" class="fiche__automate">
        Station automatique&nbsp;: l'automate fonctionne 24&nbsp;h&nbsp;/&nbsp;24, et aucun horaire
        d'accueil n'est publié.
      </p>
      <p v-else-if="sansAccueil" class="fiche__automate">
        Aucun horaire d'ouverture n'est publié pour cette station.
      </p>
      <p v-else-if="horaires.automate_24_24" class="fiche__automate">
        Automate accessible 24&nbsp;h&nbsp;/&nbsp;24. Horaires d'accueil&nbsp;:
      </p>
      <dl v-if="!sansAccueil" class="fiche__semaine">
        <template v-for="jour in horaires.jours" :key="jour.jour">
          <dt>{{ jour.nom }}</dt>
          <dd v-if="jour.ferme || !jour.plages.length">fermé</dd>
          <dd v-else>
            <span v-for="(plage, i) in jour.plages" :key="i">
              <template v-if="i > 0">, </template>{{ plage[0] }} – {{ plage[1] }}
            </span>
          </dd>
        </template>
      </dl>
    </section>

    <footer class="fiche__pied">
      <p>
        Station vue pour la première fois le {{ dateEtHeure(new Date(fiche.premiere_vue)) }},
        dernière fois le {{ dateEtHeure(new Date(fiche.derniere_vue)) }}.
      </p>
      <p v-if="fiche.enseigne">
        Enseigne « {{ fiche.enseigne.nom }} » d'après OpenStreetMap, ©&nbsp;les contributeurs
        d'OpenStreetMap (ODbL)<template v-if="fiche.enseigne.objet_osm"
          >, objet {{ fiche.enseigne.objet_osm }}</template
        >.
        <!-- La provenance est affichee, et pas seulement l'enseigne : un rapprochement
             geographique merite plus de prudence qu'une correspondance d'identifiant,
             et le lecteur doit pouvoir en juger. -->
        <template v-if="fiche.enseigne.source === 'osm-spatial'">
          Rapprochement par proximité géographique, moins sûr qu'une correspondance
          d'identifiant<template v-if="fiche.enseigne.score">
            (indice de confiance {{ fiche.enseigne.score }})</template
          >.
        </template>
      </p>
    </footer>
  </article>
</template>

<style scoped>
.fiche {
  display: grid;
  gap: var(--e-12);
  padding: var(--e-6) var(--gouttiere) var(--e-16);
  /* `minmax(0, …)` et non `1fr` : sans lui, une ligne longue impose sa largeur a la
     grille et fait deborder la page. Mesure au Jalon 1, a 375 px. */
  grid-template-columns: minmax(0, 1fr);
  max-inline-size: var(--mesure);
  margin-inline: auto;
}

.fiche h2 {
  margin: 0 0 var(--e-4);
  font-family: var(--police-titre);
  font-size: var(--t-l);
  font-weight: 500;
  line-height: var(--interligne-titre);
}

.fiche__entete {
  display: grid;
  gap: var(--e-2);
}

.fiche__fil {
  margin: 0;
  font-size: var(--t-s);
}

.fiche__fil a {
  color: var(--terracotta-texte);
}

.fiche__nom {
  margin: 0;
  font-family: var(--police-titre);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: var(--interligne-titre);
  /* Les adresses du flux sont en capitales : on les remet en casse normale sans
     toucher a la donnee. */
  text-transform: none;
}

.fiche__lieu {
  margin: 0;
  color: var(--encre-2);
}

.fiche__reperes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  align-items: center;
  margin: var(--e-2) 0 0;
  font-size: var(--t-xs);
}

.fiche__reperes > span {
  padding: var(--e-1) var(--e-2);
  border: 1px solid var(--bordure);
  border-radius: var(--rayon-bouton);
  color: var(--encre-2);
}

.fiche__ouvert {
  border-color: var(--olive-texte) !important;
  color: var(--olive-texte) !important;
}

.fiche__ferme {
  border-color: var(--terracotta-texte) !important;
  color: var(--terracotta-texte) !important;
}

.fiche__pompe {
  /* Le numero de pompe : chiffres tabulaires, comme sur une borne. */
  font-family: var(--police-mono);
  font-variant-numeric: tabular-nums;
}

.fiche__sans-enseigne,
.fiche__source,
.fiche__pied {
  margin: 0;
  color: var(--encre-2);
  font-size: var(--t-xs);
  line-height: var(--interligne-texte);
}

.fiche__pied {
  display: grid;
  gap: var(--e-1);
  padding-block-start: var(--e-6);
  border-block-start: 1px solid var(--ligne);
}

.fiche__liste {
  display: grid;
  gap: var(--e-6);
  margin: 0;
  padding: 0;
  list-style: none;
}

.fiche__carburant {
  display: grid;
  gap: var(--e-1);
  justify-items: start;
}

.fiche__aucun,
.fiche__ruptures,
.fiche__automate {
  margin: var(--e-4) 0 0;
  color: var(--encre-2);
  font-size: var(--t-s);
}

.fiche__choix {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  margin-block-end: var(--e-4);
}

.fiche__onglet {
  min-block-size: var(--cible-min);
  min-inline-size: var(--cible-min);
  padding-inline: var(--e-3);
  border: 1px solid var(--bordure);
  border-radius: var(--rayon-bouton);
  background: transparent;
  color: var(--encre);
  font: inherit;
  font-size: var(--t-s);
  cursor: pointer;
}

.fiche__onglet--actif {
  border-color: var(--encre);
  background: var(--surface);
  font-weight: 600;
}

.fiche__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.fiche__tags li {
  padding: var(--e-1) var(--e-3);
  border: 1px solid var(--ligne);
  border-radius: var(--rayon-pastille);
  font-size: var(--t-xs);
  color: var(--encre-2);
}

.fiche__semaine {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--e-1) var(--e-4);
  margin: var(--e-4) 0 0;
  font-size: var(--t-s);
}

.fiche__semaine dt {
  color: var(--encre-2);
}

.fiche__semaine dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}
</style>
