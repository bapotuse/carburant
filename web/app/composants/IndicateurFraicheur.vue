<script setup lang="ts">
/**
 * L'âge d'un prix, dit en clair.
 *
 * Règle du projet : **un prix n'est jamais affiché sans sa date**. Ce composant
 * porte cette règle. La couleur ne suffit jamais — le texte dit toujours l'âge, et
 * les classes `ancien` et `perime` ajoutent un avertissement explicite.
 */
import type { Fraicheur } from '../composables/api'
import { ageRelatif, dateEtHeure } from '../composables/formats'

const { maj, fraicheur } = defineProps<{
  /** Date du dernier changement de prix, en ISO 8601. */
  maj: string
  fraicheur: Fraicheur
}>()

const instant = computed(() => new Date(maj))
const relatif = computed(() => ageRelatif(instant.value))
const precis = computed(() => dateEtHeure(instant.value))

const AVERTISSEMENTS: Partial<Record<Fraicheur, string>> = {
  ancien: 'ce prix a plus d’une semaine',
  perime: 'ce prix a plus d’un mois',
}
const avertissement = computed(() => AVERTISSEMENTS[fraicheur])
</script>

<template>
  <span class="fraicheur" :class="`fraicheur--${fraicheur}`">
    <!-- `time` porte la date exacte : lisible par une machine, et au survol. -->
    <time :datetime="maj" :title="precis">{{ relatif }}</time>
    <span v-if="avertissement" class="fraicheur__avertissement"> — {{ avertissement }}</span>
  </span>
</template>

<style scoped>
.fraicheur {
  font-size: var(--t-xs);
  color: var(--encre-2);
}

.fraicheur--frais {
  color: var(--fraicheur-frais);
}

.fraicheur--recent {
  color: var(--fraicheur-recent);
}

.fraicheur--ancien {
  color: var(--fraicheur-ancien);
}

.fraicheur--perime {
  color: var(--fraicheur-perime);
}

.fraicheur__avertissement {
  font-style: italic;
}
</style>
