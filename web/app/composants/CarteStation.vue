<script setup lang="ts">
/**
 * Une station dans la liste des résultats.
 *
 * Le prix est le héros : il est plus grand que tout le reste et aligné à droite,
 * pour qu'on puisse comparer une colonne de prix d'un coup d'œil.
 *
 * **L'identité d'une station est son enseigne quand on la connaît, son adresse
 * sinon.** Le flux officiel ne publie ni nom ni enseigne ; celles-ci viennent
 * d'OpenStreetMap, qui en couvre plus de 99 stations sur 100. Quand elle manque, on
 * n'invente pas un nom pour combler le vide — l'adresse fait l'identité.
 *
 * La carte entière mène à la fiche, sauf le lien d'itinéraire : deux cibles
 * imbriquées sont invalides en HTML et imprévisibles au doigt. Le lien couvre donc le
 * titre, et la carte relaie le clic.
 */
import type { Station } from '../composables/api'
import { adresseLisible, distanceKm } from '../composables/formats'

const { station, rang } = defineProps<{
  station: Station
  /** Position dans la liste, à partir de 1. Le premier est mis en avant. */
  rang: number
}>()

/** Le prix affiché : celui du carburant demandé, donc le premier de la liste. */
const prix = computed(() => station.prix[0])

/** Le titre : l'enseigne si OpenStreetMap la connaît, sinon l'adresse lisible. */
const titre = computed(
  () => station.enseigne?.nom ?? (station.adresse ? adresseLisible(station.adresse) : 'Station'),
)

/** Sous le titre : l'adresse, et la ville. Sans répéter le titre quand il l'est déjà. */
const lieu = computed(() => {
  const morceaux = station.enseigne?.nom
    ? [station.adresse ? adresseLisible(station.adresse) : null, station.ville]
    : [station.ville]
  return morceaux.filter(Boolean).join(', ')
})

/** Liens d'itinéraire. L'ordre s'adapte à la plateforme au Jalon 5. */
const itineraire = computed(
  () =>
    `https://www.google.com/maps/dir/?api=1&destination=${station.latitude},${station.longitude}`,
)
</script>

<template>
  <li class="station" :class="{ 'station--premier': rang === 1 }">
    <div class="station__identite">
      <p class="station__titre">
        <NuxtLink class="station__lien" :to="`/station/${station.id}`">{{ titre }}</NuxtLink>
      </p>
      <p v-if="lieu" class="station__lieu">{{ lieu }}</p>
      <p class="station__repere">
        <span>{{ distanceKm(station.distance_km) }}</span>
        <span v-if="station.autoroute" class="station__autoroute">autoroute</span>
      </p>
      <IndicateurFraicheur
        v-if="prix?.maj && prix.fraicheur"
        :maj="prix.maj"
        :fraicheur="prix.fraicheur"
      />
    </div>

    <div class="station__prix">
      <PrixTotem v-if="prix?.prix_eur_l" :prix-eur-l="prix.prix_eur_l" />
      <a class="station__aller" :href="itineraire" target="_blank" rel="noopener"> Y aller </a>
    </div>
  </li>
</template>

<style scoped>
.station {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--e-4);
  align-items: start;
  padding-block: var(--e-4);
  border-block-end: 1px solid var(--ligne);
}

/* La moins chère se distingue par un filet, pas par une carte ni une ombre. */
.station--premier {
  border-inline-start: 3px solid var(--terracotta);
  padding-inline-start: var(--e-3);
  margin-inline-start: calc(var(--e-3) * -1);
}

.station__identite {
  display: grid;
  gap: var(--e-1);
  min-inline-size: 0;
}

.station__titre {
  margin: 0;
  font-size: var(--t-m);
  font-weight: 600;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.station__lien {
  display: inline-block;
  /* La cible fait 44 px de haut sans grossir le texte : c'est le `padding` vertical
     qui porte la hauteur, pas la police. Mesure exigee par docs/specs/web.md et
     verifiee par un test Playwright. */
  padding-block: var(--e-2);
  color: var(--encre);
  text-decoration-color: var(--bordure);
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}

.station__lien:hover,
.station__lien:focus-visible {
  text-decoration-color: currentcolor;
}

.station__lieu {
  margin: 0;
  color: var(--encre-2);
  font-size: var(--t-s);
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.station__repere {
  display: flex;
  gap: var(--e-2);
  align-items: baseline;
  font-size: var(--t-xs);
  color: var(--encre-2);
  font-variant-numeric: tabular-nums;
}

.station__autoroute::before {
  content: '·';
  margin-inline-end: var(--e-2);
}

.station__prix {
  display: grid;
  justify-items: end;
  gap: var(--e-1);
}

.station__aller {
  font-size: var(--t-xs);
  /* Cible tactile de 44 px sans gonfler la ligne : on étend la zone cliquable. */
  display: inline-flex;
  align-items: center;
  min-block-size: var(--cible-min);
  padding-inline: var(--e-2);
  margin-inline-end: calc(var(--e-2) * -1);
}
</style>
