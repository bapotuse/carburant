<script setup lang="ts">
/**
 * Une station dans la liste des résultats.
 *
 * Le prix est le héros : il est plus grand que tout le reste et aligné à droite,
 * pour qu'on puisse comparer une colonne de prix d'un coup d'œil. L'adresse sert
 * d'identité, puisque le flux officiel ne donne ni nom ni enseigne.
 */
import type { Station } from '../composables/api'
import { distanceKm } from '../composables/formats'

const { station, rang } = defineProps<{
  station: Station
  /** Position dans la liste, à partir de 1. Le premier est mis en avant. */
  rang: number
}>()

/** Le prix affiché : celui du carburant demandé, donc le premier de la liste. */
const prix = computed(() => station.prix[0])

const lieu = computed(() => [station.adresse, station.ville].filter(Boolean).join(', '))

/** Liens d'itinéraire. L'ordre s'adapte à la plateforme au Jalon 5. */
const itineraire = computed(
  () =>
    `https://www.google.com/maps/dir/?api=1&destination=${station.latitude},${station.longitude}`,
)
</script>

<template>
  <li class="station" :class="{ 'station--premier': rang === 1 }">
    <div class="station__identite">
      <p class="station__lieu">{{ lieu }}</p>
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

.station__lieu {
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
