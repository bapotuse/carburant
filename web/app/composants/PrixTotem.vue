<script setup lang="ts">
/**
 * Le prix, heros de l'ecran, a la maniere d'un totem de station.
 *
 * Trois decimales, chiffres tabulaires, derniere decimale plus petite et surelevee :
 * `1,87⁹`. La derniere decimale reduite est purement visuelle -- un lecteur d'ecran
 * entend « 1,879 euro le litre », pas « 1,87 9 ».
 *
 * Zero kilo-octet de JavaScript ajoute : tout est en CSS.
 */
const proprietes = withDefaults(
  defineProps<{
    /** Prix en euros par litre, tel qu'il vient de l'API (`prix_eur_l`). */
    prixEurL: number
    /** Taille : `l` sur la fiche station, `m` dans une liste. */
    taille?: 'm' | 'l'
    /** Affiche l'unite `/L` a cote du prix. */
    avecUnite?: boolean
  }>(),
  { taille: 'm', avecUnite: true },
)

/** Les trois decimales, separees : les deux premieres et la troisieme. */
const parties = computed(() => {
  const fixe = proprietes.prixEurL.toFixed(3)
  const [entier, decimales] = fixe.split('.') as [string, string]
  return {
    entier,
    deuxPremieres: decimales.slice(0, 2),
    troisieme: decimales.slice(2),
  }
})

/**
 * Ce que lit un lecteur d'ecran. Jamais le decoupage visuel.
 *
 * Pas de `role="text"` ici : ce role n'existe pas dans la specification ARIA, c'est
 * une extension de WebKit. Un `aria-label` sur un `span` sans role n'est pas fiable
 * non plus. La methode qui marche partout : du texte reellement present mais
 * visuellement masque, et la version visuelle en `aria-hidden`.
 */
const pourLecteurDEcran = computed(
  () => `${proprietes.prixEurL.toFixed(3).replace('.', ',')} euro le litre`,
)
</script>

<template>
  <span class="prix" :class="`prix--${taille}`">
    <span class="lecteur-seul">{{ pourLecteurDEcran }}</span>
    <span aria-hidden="true" class="prix__valeur">
      {{ parties.entier }}<span class="prix__virgule">,</span>{{ parties.deuxPremieres
      }}<span class="prix__millieme">{{ parties.troisieme }}</span>
    </span>
    <span v-if="avecUnite" aria-hidden="true" class="prix__unite">&#8239;€/L</span>
  </span>
</template>

<style scoped>
.prix {
  display: inline-flex;
  align-items: baseline;
  font-family: var(--police-prix);
  /* Chiffres tabulaires : sans quoi les colonnes de prix dansent d'une ligne a
   * l'autre. Une police qui ne repond pas a `tnum` est eliminee d'office. */
  font-feature-settings: 'tnum' 1;
  font-variant-numeric: tabular-nums;
  line-height: var(--interligne-prix);
  color: var(--encre);
}

.prix__valeur {
  font-size: var(--t-prix);
  font-weight: 600;
  letter-spacing: -0.01em;
}

.prix--l .prix__valeur {
  font-size: var(--t-prix-l);
}

.prix__virgule {
  /* La virgule prend trop de place a cette taille : on la resserre. */
  margin-inline: -0.04em;
}

.prix__millieme {
  font-size: 0.58em;
  vertical-align: baseline;
  /* Le millieme remonte, comme sur un afficheur de pompe. */
  position: relative;
  inset-block-end: 0.33em;
  margin-inline-start: 0.02em;
}

.prix__unite {
  font-family: var(--police-texte);
  font-size: var(--t-s);
  font-weight: 500;
  color: var(--encre-2);
  margin-inline-start: 0.15em;
}
</style>
