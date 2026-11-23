<script setup lang="ts">
/**
 * Recapitulatif d'un plein, presente comme un ticket de caisse : police
 * monospace, bord dentele, total en bas.
 *
 * Le bord dentele est obtenu par un `mask-image` en CSS : aucune image, aucun
 * kilo-octet. Les montants sont formates a la francaise, avec des espaces
 * insecables fines.
 */
const {
  lignes,
  total,
  mention = '',
} = defineProps<{
  lignes: { intitule: string; valeur: string }[]
  total: { intitule: string; valeur: string }
  /** Mention de bas de ticket : la date de mise a jour, par exemple. */
  mention?: string
}>()
</script>

<template>
  <div class="ticket">
    <p class="ticket__entete">Au compteur</p>
    <dl class="ticket__lignes">
      <template v-for="ligne in lignes" :key="ligne.intitule">
        <dt>{{ ligne.intitule }}</dt>
        <dd>{{ ligne.valeur }}</dd>
      </template>
    </dl>
    <hr class="ticket__filet" />
    <dl class="ticket__total">
      <dt>{{ total.intitule }}</dt>
      <dd>{{ total.valeur }}</dd>
    </dl>
    <p v-if="mention" class="ticket__mention">{{ mention }}</p>
  </div>
</template>

<style scoped>
.ticket {
  --dent: 7px;
  font-family: var(--police-mono);
  font-size: var(--t-s);
  background: var(--fond);
  color: var(--encre);
  padding: var(--e-4) var(--e-4) var(--e-6);
  max-inline-size: 20rem;
  border: 1px solid var(--ligne);
  /* Bord dentele en bas, comme un ticket arrache. */
  mask-image: radial-gradient(var(--dent) at var(--dent) 100%, transparent 98%, black 100%);
  mask-size: calc(var(--dent) * 2) 100%;
  mask-repeat: repeat-x;
  mask-position: 0 0;
}

.ticket__entete {
  font-size: var(--t-xs);
  letter-spacing: 0.08em;
  color: var(--encre-2);
  margin-block-end: var(--e-3);
}

.ticket__lignes,
.ticket__total {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--e-1) var(--e-4);
  font-variant-numeric: tabular-nums;
}

.ticket__lignes dd,
.ticket__total dd {
  text-align: right;
}

.ticket__filet {
  border: 0;
  border-block-start: 1px dashed var(--bordure);
  margin-block: var(--e-3);
}

.ticket__total {
  font-weight: 600;
  font-size: var(--t-m);
}

.ticket__mention {
  margin-block-start: var(--e-3);
  font-size: var(--t-xs);
  color: var(--encre-2);
}
</style>
