<script setup lang="ts">
/**
 * Jauge E -> F pour saisir l'autonomie restante.
 *
 * C'est un VRAI controle, pas une decoration : un `input type=range` natif, habille.
 * Il garde donc gratuitement le clavier (fleches, Origine, Fin), le focus, le
 * glissement au doigt et l'annonce de la valeur par les lecteurs d'ecran.
 *
 * Le voyant de reserve s'allume sous 50 km : c'est une information, pas un effet.
 */
const modele = defineModel<number>({ required: true })

const { max = 800 } = defineProps<{
  /** Autonomie maximale saisissable, en kilometres. */
  max?: number
}>()

const SEUIL_RESERVE = 50

const enReserve = computed(() => modele.value <= SEUIL_RESERVE)
/** Position de l'aiguille, de 0 (E) a 1 (F). */
const fraction = computed(() => Math.min(1, Math.max(0, modele.value / max)))
/** L'aiguille balaie 120 degres, comme un cadran de tableau de bord. */
const angle = computed(() => -60 + fraction.value * 120)
const identifiant = useId()
</script>

<template>
  <div class="jauge">
    <label class="jauge__intitule" :for="identifiant">Autonomie restante</label>

    <div class="jauge__cadran" aria-hidden="true">
      <svg viewBox="0 0 120 72" class="jauge__svg">
        <path
          d="M 14 64 A 46 46 0 0 1 106 64"
          fill="none"
          stroke="var(--ligne)"
          stroke-width="6"
          stroke-linecap="round"
        />
        <path
          d="M 14 64 A 46 46 0 0 1 106 64"
          fill="none"
          stroke="var(--terracotta)"
          stroke-width="6"
          stroke-linecap="round"
          :stroke-dasharray="`${fraction * 144} 144`"
        />
        <text x="12" y="71" class="jauge__repere">E</text>
        <text x="104" y="71" class="jauge__repere">F</text>
        <g :style="{ rotate: `${angle}deg` }" class="jauge__aiguille">
          <line x1="60" y1="64" x2="60" y2="26" stroke="var(--encre)" stroke-width="2.5" />
          <circle cx="60" cy="64" r="4" fill="var(--encre)" />
        </g>
      </svg>
      <span v-if="enReserve" class="jauge__voyant">Réserve</span>
    </div>

    <input
      :id="identifiant"
      v-model.number="modele"
      class="jauge__curseur"
      type="range"
      min="0"
      :max="max"
      step="10"
      :aria-valuetext="`${modele} kilomètres d'autonomie`"
    />

    <output class="jauge__valeur" :for="identifiant"> {{ modele }}&#8239;km </output>
  </div>
</template>

<style scoped>
.jauge {
  display: grid;
  gap: var(--e-2);
  justify-items: center;
  max-inline-size: 18rem;
}

.jauge__intitule {
  font-size: var(--t-s);
  font-weight: 500;
  color: var(--encre-2);
  justify-self: start;
}

.jauge__cadran {
  position: relative;
  inline-size: 100%;
}

.jauge__svg {
  inline-size: 100%;
  block-size: auto;
}

.jauge__repere {
  font-family: var(--police-texte);
  font-size: 9px;
  font-weight: 600;
  fill: var(--encre-2);
}

.jauge__aiguille {
  transform-origin: 60px 64px;
  transition: rotate var(--duree-moyenne) var(--courbe);
}

.jauge__voyant {
  position: absolute;
  inset-block-end: 0;
  inset-inline-start: 50%;
  translate: -50% 0;
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--terracotta-texte);
}

.jauge__curseur {
  inline-size: 100%;
  accent-color: var(--terracotta);
}

.jauge__valeur {
  font-family: var(--police-prix);
  font-feature-settings: 'tnum' 1;
  font-size: var(--t-l);
  font-weight: 600;
}
</style>
