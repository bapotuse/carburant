<script setup lang="ts">
/**
 * Accueil : une seule action évidente, « où faire le plein ? ».
 *
 * La recherche est **en bas de l'écran**, dans la zone du pouce, et les résultats
 * remontent au-dessus. C'est inhabituel pour une page d'accueil, et c'est volontaire :
 * on cherche de l'essence au volant ou à côté de sa voiture, d'une main.
 *
 * Aucun prix n'est affiché sans sa date. Aucun chiffre n'est inventé : les totaux
 * viennent de `/v1/meta`.
 */
import {
  ErreurAPI,
  ErreurReseau,
  type Station,
  type StationsProches,
  stationsProches,
} from '../composables/api'
import { baseApi } from '../composables/api'
import { ageRelatif, entier } from '../composables/formats'

type Lieu = { latitude: number; longitude: number; libelle: string }

const CARBURANTS = [
  { code: 'gazole', libelle: 'Gazole' },
  { code: 'e10', libelle: 'SP95-E10' },
  { code: 'sp98', libelle: 'SP98' },
  { code: 'sp95', libelle: 'SP95' },
  { code: 'e85', libelle: 'E85' },
  { code: 'gplc', libelle: 'GPLc' },
] as const

const carburant = ref<string>('gazole')
const lieu = ref<Lieu | null>(null)
const resultat = ref<StationsProches | null>(null)
const charge = ref(false)
const erreur = ref<string | null>(null)

/** L'état des données, pour le pied de page. Chargé une fois, côté serveur. */
const { data: etat } = await useAsyncData(
  'meta',
  () =>
    $fetch<{ stations_actives: number; derniere_collecte: string | null }>(`${baseApi()}/v1/meta`),
  // Si l'API ne répond pas, la page s'affiche quand même : elle dit simplement
  // « toutes les stations » au lieu d'un nombre, et ne ment sur rien.
  { default: () => null },
)

const stations = computed<Station[]>(() => resultat.value?.stations ?? [])

async function chercher(): Promise<void> {
  if (!lieu.value) return
  charge.value = true
  erreur.value = null
  try {
    resultat.value = await stationsProches({
      lat: lieu.value.latitude,
      lon: lieu.value.longitude,
      carburant: carburant.value,
      rayonKm: 10,
      limite: 20,
    })
  } catch (e) {
    resultat.value = null
    erreur.value =
      e instanceof ErreurAPI || e instanceof ErreurReseau
        ? e.message
        : "Quelque chose n'a pas fonctionné. Réessayez dans un instant."
  } finally {
    charge.value = false
  }
}

function surLieuChoisi(choisi: Lieu): void {
  lieu.value = choisi
  void chercher()
}

// Changer de carburant relance la recherche sur le même lieu.
watch(carburant, () => {
  if (lieu.value) void chercher()
})

const collecte = computed(() =>
  etat.value?.derniere_collecte ? ageRelatif(new Date(etat.value.derniere_collecte)) : null,
)

useHead({
  title: 'Carburant — où faire le plein ?',
  meta: [
    {
      name: 'description',
      content:
        'Les prix des carburants des stations-service de France, collectés toutes les ' +
        '15 minutes depuis le flux ouvert de la DGCCRF. Chaque prix est affiché avec ' +
        'sa date de mise à jour.',
    },
  ],
})
</script>

<template>
  <div class="page">
    <main id="principal" class="resultats">
      <!-- État initial : on dit ce que fait le site, sans promesse creuse. -->
      <section v-if="!lieu && !charge" class="accueil">
        <h1>Où faire le plein&nbsp;?</h1>
        <p class="accueil__intro">
          Les prix de
          <strong v-if="etat">{{ entier(etat.stations_actives) }}</strong>
          <strong v-else>toutes les</strong>
          stations-service de France, collectés toutes les 15&nbsp;minutes depuis le flux ouvert de
          la DGCCRF.
        </p>
        <p class="accueil__intro">Indiquez une adresse, ou utilisez votre position.</p>
        <hr class="marquage" />
        <p class="accueil__note">
          Chaque prix est affiché avec sa date de mise à jour. Un prix de plus d'un mois n'apparaît
          pas dans les résultats.
        </p>
      </section>

      <!-- Chargement : un squelette à la forme du contenu attendu, pas un spinner. -->
      <section v-else-if="charge" class="squelette" aria-busy="true" aria-live="polite">
        <p class="lecteur-seul">Recherche des stations…</p>
        <div v-for="n in 4" :key="n" class="squelette__ligne">
          <span class="squelette__texte" />
          <span class="squelette__prix" />
        </div>
      </section>

      <section v-else-if="erreur" class="message" role="alert">
        <h1>Ça n'a pas marché</h1>
        <p>{{ erreur }}</p>
      </section>

      <section v-else-if="stations.length === 0" class="message">
        <h1>Aucune station à moins de 10&nbsp;km</h1>
        <p>
          Aucune station ne vend du
          {{ CARBURANTS.find((c) => c.code === carburant)?.libelle }} près de {{ lieu?.libelle }},
          ou leurs prix datent de plus d'un mois.
        </p>
        <p class="message__piste">Essayez un autre carburant, ou un autre lieu.</p>
      </section>

      <section v-else class="liste">
        <h1 class="liste__titre">
          {{ CARBURANTS.find((c) => c.code === carburant)?.libelle }} près de
          {{ lieu?.libelle }}
        </h1>
        <p class="liste__compte">
          {{ stations.length }} station{{ stations.length > 1 ? 's' : '' }}, de la moins chère à la
          plus chère
        </p>
        <ul class="liste__stations">
          <CarteStation
            v-for="(station, index) in stations"
            :key="station.id"
            :station="station"
            :rang="index + 1"
          />
        </ul>
        <p v-if="collecte" class="liste__collecte">
          Données collectées {{ collecte }}. Les prix portent la date à laquelle la station les a
          changés.
        </p>
      </section>
    </main>

    <!-- Zone du pouce : tout ce qui se touche est ici, en bas. -->
    <div class="commandes">
      <fieldset class="carburants">
        <legend class="lecteur-seul">Carburant</legend>
        <label v-for="c in CARBURANTS" :key="c.code" class="carburants__choix">
          <input v-model="carburant" type="radio" name="carburant" :value="c.code" />
          <PastilleCarburant :code="c.code" />
        </label>
      </fieldset>

      <ChampAdresse @choisi="surLieuChoisi" @erreur="(m) => (erreur = m)" />
    </div>
  </div>
</template>

<style scoped>
.page {
  display: grid;
  /* La page occupe la hauteur visible : les résultats défilent, la barre reste. */
  grid-template-rows: 1fr auto;
  min-block-size: 100dvh;
  max-inline-size: 40rem;
  margin-inline: auto;
}

.resultats {
  padding-block: var(--e-8) var(--e-6);
  overflow-y: auto;
}

/* ------------------------------------------------------------ état initial */
.accueil {
  display: grid;
  gap: var(--e-4);
  justify-items: start;
}

.accueil__intro {
  font-size: var(--t-l);
  line-height: 1.45;
}

.accueil__note {
  font-size: var(--t-s);
  color: var(--encre-2);
}

/* ------------------------------------------------------------ chargement */
.squelette {
  display: grid;
  gap: var(--e-4);
}

.squelette__ligne {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--e-4);
  align-items: center;
  padding-block: var(--e-4);
  border-block-end: 1px solid var(--ligne);
}

.squelette__texte,
.squelette__prix {
  display: block;
  background: var(--surface);
  border-radius: 2px;
}

.squelette__texte {
  block-size: 1rem;
  inline-size: 70%;
}

.squelette__prix {
  block-size: 2.5rem;
  inline-size: 6rem;
}

@media (prefers-reduced-motion: no-preference) {
  .squelette__texte,
  .squelette__prix {
    animation: respire 1.4s ease-in-out infinite;
  }

  @keyframes respire {
    50% {
      opacity: 0.55;
    }
  }
}

/* ------------------------------------------------------------ messages */
.message {
  display: grid;
  gap: var(--e-3);
  justify-items: start;
}

.message__piste {
  font-size: var(--t-s);
  color: var(--encre-2);
}

/* ------------------------------------------------------------ résultats */
.liste__titre {
  font-size: var(--t-xl);
}

.liste__compte {
  margin-block: var(--e-2) var(--e-4);
  font-size: var(--t-s);
  color: var(--encre-2);
}

.liste__stations {
  list-style: none;
  padding: 0;
  margin: 0;
}

.liste__collecte {
  margin-block-start: var(--e-6);
  font-size: var(--t-xs);
  color: var(--encre-2);
}

/* ------------------------------------------------------------ zone du pouce */
.commandes {
  position: sticky;
  inset-block-end: 0;
  display: grid;
  gap: var(--e-3);
  padding-block: var(--e-3);
  padding-block-end: calc(var(--e-3) + env(safe-area-inset-bottom));
  background: var(--fond);
  border-block-start: 1px solid var(--ligne);
}

.carburants {
  display: flex;
  gap: var(--e-2);
  overflow-x: auto;
  border: 0;
  padding: 0;
  margin: 0;
  /* Le doigt fait défiler les carburants sans que la page bouge. */
  scrollbar-width: none;
  overscroll-behavior-x: contain;
}

.carburants::-webkit-scrollbar {
  display: none;
}

.carburants__choix {
  flex: none;
  display: inline-flex;
  align-items: center;
  min-block-size: var(--cible-min);
  padding-inline: var(--e-3);
  border: 1px solid var(--bordure);
  border-radius: var(--rayon-pastille);
  cursor: pointer;
}

/* Le bouton radio reste présent pour le clavier et les lecteurs d'écran : il est
   masqué visuellement, pas supprimé. */
.carburants__choix input {
  position: absolute;
  inline-size: 1px;
  block-size: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}

.carburants__choix:has(input:checked) {
  background: var(--surface);
  border-color: var(--encre);
}

.carburants__choix:has(input:focus-visible) {
  outline: 2px solid var(--terracotta-texte);
  outline-offset: 2px;
}
</style>
