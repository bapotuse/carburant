<script setup lang="ts">
/**
 * « Y aller » : les trois applications d'itinéraire, et pas une seule.
 *
 * On ne choisit pas pour l'utilisateur, parce qu'on ne sait pas laquelle il a
 * installée. En revanche l'**ordre** s'adapte : sur un appareil Apple, Plans d'abord,
 * puisque c'est la seule qui est forcément là.
 *
 * **La plateforme est lue dans l'en-tête de la requête, pas après l'hydratation.** Un
 * réordonnancement côté client ferait sauter les trois boutons sous le doigt une
 * fraction de seconde après l'affichage — exactement sous le pouce, et exactement au
 * moment où on appuie. Lire l'en-tête donne le même ordre des deux côtés.
 */
const { latitude, longitude, nom } = defineProps<{
  latitude: number
  longitude: number
  /** Nom de la station, pour l'étiquette accessible du lien. */
  nom: string
}>()

interface Destination {
  readonly cle: string
  readonly libelle: string
  readonly url: string
}

const entetes = useRequestHeaders(['user-agent'])
/** Vrai pour iPhone, iPad et Mac : les appareils où Plans est préinstallé. */
const pomme = computed(() => /iphone|ipad|ipod|macintosh/i.test(entetes['user-agent'] ?? ''))

const destinations = computed<Destination[]>(() => {
  const coordonnees = `${latitude},${longitude}`
  const plans: Destination = {
    cle: 'plans',
    libelle: 'Plans',
    url: `https://maps.apple.com/?daddr=${coordonnees}`,
  }
  const google: Destination = {
    cle: 'google',
    libelle: 'Google Maps',
    url: `https://www.google.com/maps/dir/?api=1&destination=${coordonnees}`,
  }
  const waze: Destination = {
    cle: 'waze',
    libelle: 'Waze',
    url: `https://waze.com/ul?ll=${coordonnees}&navigate=yes`,
  }
  return pomme.value ? [plans, google, waze] : [google, plans, waze]
})
</script>

<template>
  <nav class="itineraire" aria-label="Itinéraire">
    <p class="itineraire__titre">Y aller</p>
    <ul class="itineraire__liste">
      <li v-for="destination in destinations" :key="destination.cle">
        <a
          class="itineraire__lien"
          :href="destination.url"
          target="_blank"
          rel="noopener"
          :aria-label="`Itinéraire vers ${nom} avec ${destination.libelle}`"
        >
          {{ destination.libelle }}
        </a>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.itineraire__titre {
  margin: 0 0 var(--e-2);
  font-size: var(--t-s);
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--encre-2);
}

.itineraire__liste {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.itineraire__lien {
  display: flex;
  align-items: center;
  /* 44 px exiges par la spec mobile, et verifies par un test Playwright. */
  min-block-size: var(--cible-min);
  padding-inline: var(--e-3);
  border: 1px solid var(--bordure);
  border-radius: var(--rayon-bouton);
  color: var(--encre);
  font-size: var(--t-m);
  text-decoration: none;
}

.itineraire__lien:hover,
.itineraire__lien:focus-visible {
  background: var(--surface);
}
</style>
