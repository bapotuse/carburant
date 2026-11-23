<script setup lang="ts">
/**
 * Pastille de carburant, a la forme des etiquettes europeennes EN 16942 :
 * cercle pour les essences, carre pour le gazole, losange pour le GPL.
 *
 * Trois encodages redondants du meme sens -- couleur, forme et libelle -- pour que la
 * couleur ne soit jamais seule porteuse de l'information. En theme sombre, le plancher
 * de contraste de 4,5:1 rend les six couleurs quasi iso-luminantes : ce sont alors la
 * forme et le libelle qui font tout le travail.
 */
type Code = 'gazole' | 'sp95' | 'e10' | 'sp98' | 'e85' | 'gplc'

const { code, libelleVisible = true } = defineProps<{
  code: Code
  /** Masque le libelle visuellement, en le gardant pour les lecteurs d'ecran. */
  libelleVisible?: boolean
}>()

const LIBELLES: Record<Code, string> = {
  gazole: 'Gazole',
  sp95: 'SP95',
  e10: 'SP95-E10',
  sp98: 'SP98',
  e85: 'E85',
  gplc: 'GPLc',
}

/** Forme EN 16942 : B7 en carre, les essences en cercle, le GPL en losange. */
const FORMES: Record<Code, 'cercle' | 'carre' | 'losange'> = {
  gazole: 'carre',
  sp95: 'cercle',
  e10: 'cercle',
  sp98: 'cercle',
  e85: 'cercle',
  gplc: 'losange',
}

const libelle = computed(() => LIBELLES[code])
const forme = computed(() => FORMES[code])
/** Le token de couleur du carburant, injecte comme custom property locale. */
const couleur = computed(() => ({ '--couleur': `var(--carburant-${code})` }))
</script>

<template>
  <span class="pastille">
    <span
      class="pastille__marque"
      :class="`pastille__marque--${forme}`"
      :style="couleur"
      aria-hidden="true"
    />
    <span :class="libelleVisible ? 'pastille__libelle' : 'lecteur-seul'">{{ libelle }}</span>
  </span>
</template>

<style scoped>
.pastille {
  display: inline-flex;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-s);
  font-weight: 500;
  color: var(--encre);
}

.pastille__marque {
  inline-size: 0.875rem;
  block-size: 0.875rem;
  flex: none;
  background: var(--couleur);
}

.pastille__marque--cercle {
  border-radius: var(--rayon-pastille);
}

.pastille__marque--carre {
  border-radius: 1px;
}

.pastille__marque--losange {
  border-radius: 1px;
  rotate: 45deg;
  scale: 0.86;
}

.pastille__libelle {
  white-space: nowrap;
}
</style>
