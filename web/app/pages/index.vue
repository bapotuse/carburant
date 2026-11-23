<script setup lang="ts">
/**
 * Accueil.
 *
 * Au Jalon 0, le socle est en place mais l'ETL et l'API ne servent encore aucune
 * donnee : cette page le dit franchement plutot que d'afficher une maquette qui
 * laisserait croire a un service qui fonctionne. L'accueil reel -- champ d'adresse,
 * bouton « Ma position », liste triee par prix -- arrive au Jalon 1.
 */
useHead({
  title: 'Carburant — prix des carburants en France',
  meta: [
    {
      name: 'description',
      content:
        'Prix des carburants en France, collectés toutes les 15 minutes depuis le flux ' +
        'ouvert de la DGCCRF. Chaque prix est affiché avec sa date de mise à jour.',
    },
  ],
})
</script>

<template>
  <main id="principal" class="accueil">
    <h1>Où faire le plein&nbsp;?</h1>
    <p>
      Les prix de 9&#8239;826 stations-service en France, collectés toutes les 15 minutes depuis le
      flux ouvert de la DGCCRF. Chaque prix est affiché avec sa date de mise à jour.
    </p>
    <hr class="marquage" />
    <p class="accueil__etat">
      Jalon 0 — le socle technique est en place. La recherche de station arrive au Jalon 1, quand
      l'ETL alimentera la base. Rien n'est affiché tant qu'il n'y a pas de vraie donnée à afficher.
    </p>
    <p><NuxtLink to="/planche-de-style">Voir la planche de style</NuxtLink></p>
  </main>
</template>

<style scoped>
.accueil {
  max-inline-size: 42rem;
  margin-inline: auto;
  padding-block: var(--e-12) var(--e-24);
  display: grid;
  gap: var(--e-6);
  justify-items: start;
}

.accueil__etat {
  font-size: var(--t-s);
  color: var(--encre-2);
}
</style>
