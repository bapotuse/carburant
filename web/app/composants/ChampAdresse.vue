<script setup lang="ts">
/**
 * Champ d'adresse avec suggestions, et bouton « Ma position ».
 *
 * Trois règles de `docs/specs/web.md` sont tenues ici :
 *
 * - **anti-rebond** : on n'interroge pas le géocodeur à chaque frappe. Le quota de
 *   l'IGN est partagé, et une requête par caractère serait un gaspillage.
 * - **la géolocalisation n'est demandée qu'au clic**, jamais au chargement. Une page
 *   qui demande la position à l'ouverture est une page qu'on referme.
 * - **police ≥ 16 px dans le champ**, sinon iOS zoome tout seul au focus et l'écran
 *   part de travers.
 *
 * Quand le géocodeur dit `ambigu`, on affiche les candidats et on ne choisit pas :
 * « le Prado » à Marseille désigne deux avenues distantes de 1,2 km.
 */
import { type Candidat, ErreurAPI, ErreurReseau, geocoder } from '../composables/api'

const emit = defineEmits<{
  /** Un lieu a été choisi : coordonnées et libellé affichable. */
  choisi: [{ latitude: number; longitude: number; libelle: string }]
  /** Une erreur à montrer à l'utilisateur. */
  erreur: [string]
}>()

const ANTI_REBOND_MS = 350
/** Mesuré : en dessous de 3 caractères, le géocodeur renvoie du bruit. */
const LONGUEUR_MINIMALE = 3

const texte = ref('')
const candidats = ref<Candidat[]>([])
const ambigu = ref(false)
/** Le géocodeur a répondu, et n'a rien trouvé. Sans cela, l'écran reste muet. */
const vide = ref(false)
const cherche = ref(false)
const localise = ref(false)
const identifiant = useId()

let minuteur: ReturnType<typeof setTimeout> | undefined
let derniereRequete = 0

async function interroger(valeur: string): Promise<void> {
  const requete = ++derniereRequete
  cherche.value = true
  try {
    const resultat = await geocoder(valeur)
    // Une réponse arrivée après une frappe plus récente ne doit pas l'écraser.
    if (requete !== derniereRequete) return
    candidats.value = resultat.candidats
    ambigu.value = resultat.ambigu
    vide.value = resultat.candidats.length === 0
    // `resultat.raison` est volontairement ignorée : elle est écrite pour l'API et
    // pour le serveur MCP (« le meilleur candidat ne marque que 0,608 »), pas pour
    // quelqu'un qui cherche une station. Un score n'explique rien à personne.
  } catch (erreur) {
    if (requete !== derniereRequete) return
    candidats.value = []
    emit('erreur', messageDe(erreur))
  } finally {
    if (requete === derniereRequete) cherche.value = false
  }
}

function messageDe(erreur: unknown): string {
  if (erreur instanceof ErreurAPI || erreur instanceof ErreurReseau) return erreur.message
  return "Quelque chose n'a pas fonctionné. Réessayez dans un instant."
}

watch(texte, (valeur) => {
  clearTimeout(minuteur)
  const propre = valeur.trim()
  if (propre.length < LONGUEUR_MINIMALE) {
    candidats.value = []
    ambigu.value = false
    vide.value = false
    return
  }
  minuteur = setTimeout(() => void interroger(propre), ANTI_REBOND_MS)
})

onBeforeUnmount(() => clearTimeout(minuteur))

function choisir(candidat: Candidat): void {
  texte.value = candidat.libelle
  candidats.value = []
  ambigu.value = false
  vide.value = false
  emit('choisi', {
    latitude: candidat.latitude,
    longitude: candidat.longitude,
    libelle: candidat.libelle,
  })
}

function valider(): void {
  // Entrée prend le premier candidat, sauf si c'est ambigu : dans ce cas on laisse
  // la liste ouverte plutôt que de deviner.
  const premier = candidats.value[0]
  if (premier && !ambigu.value) choisir(premier)
}

function maPosition(): void {
  if (!('geolocation' in navigator)) {
    emit('erreur', 'Votre navigateur ne sait pas donner votre position. Saisissez une adresse.')
    return
  }
  localise.value = true
  navigator.geolocation.getCurrentPosition(
    (position) => {
      localise.value = false
      texte.value = 'Ma position'
      candidats.value = []
      vide.value = false
      emit('choisi', {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        libelle: 'Votre position',
      })
    },
    (erreur) => {
      localise.value = false
      const messages: Record<number, string> = {
        1: 'Position refusée. Saisissez une adresse à la place.',
        2: 'Position indisponible. Saisissez une adresse à la place.',
        3: 'La localisation a pris trop de temps. Saisissez une adresse.',
      }
      emit('erreur', messages[erreur.code] ?? 'Position indisponible. Saisissez une adresse.')
    },
    { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
  )
}
</script>

<template>
  <div class="recherche">
    <!-- Les suggestions sont au-dessus du champ : le champ est en bas de l'écran,
         dans la zone du pouce, et une liste qui descendrait sortirait de l'écran. -->
    <ul v-if="candidats.length" id="suggestions" class="suggestions" role="listbox">
      <li v-if="ambigu" class="suggestions__note" role="presentation">
        Plusieurs lieux portent ce nom. Choisissez&nbsp;:
      </li>
      <li
        v-for="candidat in candidats"
        :key="candidat.libelle"
        role="option"
        :aria-selected="false"
      >
        <button type="button" class="suggestions__choix" @click="choisir(candidat)">
          <span class="suggestions__libelle">{{ candidat.libelle }}</span>
        </button>
      </li>
    </ul>

    <form class="recherche__barre" role="search" @submit.prevent="valider">
      <label class="lecteur-seul" :for="identifiant">Adresse, ville ou code postal</label>
      <input
        :id="identifiant"
        v-model="texte"
        class="recherche__champ"
        type="search"
        inputmode="search"
        enterkeyhint="search"
        autocomplete="street-address"
        autocapitalize="off"
        spellcheck="false"
        placeholder="Adresse, ville ou code postal"
        role="combobox"
        :aria-expanded="candidats.length > 0"
        aria-controls="suggestions"
        aria-autocomplete="list"
      />
      <button type="button" class="recherche__position" :disabled="localise" @click="maPosition">
        <span aria-hidden="true" class="recherche__cible" />
        <span class="lecteur-seul">Utiliser ma position</span>
      </button>
    </form>

    <p v-if="cherche" class="recherche__etat" aria-live="polite">Recherche…</p>
    <p v-else-if="vide" class="recherche__etat" aria-live="polite">
      Aucun lieu trouvé pour «&nbsp;{{ texte.trim() }}&nbsp;». Essayez une ville ou un code postal.
    </p>
  </div>
</template>

<style scoped>
.recherche {
  display: grid;
  gap: var(--e-2);
}

.recherche__barre {
  display: flex;
  gap: var(--e-2);
}

.recherche__champ {
  flex: 1;
  min-inline-size: 0;
  padding: var(--e-3) var(--e-4);
  /* ≥ 16 px : en dessous, iOS zoome au focus. */
  font-size: max(1rem, var(--t-m));
  background: var(--fond);
  color: var(--encre);
  border: 1px solid var(--bordure);
  border-radius: var(--rayon-champ);
}

/* La croix d'effacement native de `type="search"` est bleue dans Chrome et grise
   dans Safari : dans les deux cas, hors palette. On la redessine à l'encre du
   site, en gardant le contrôle natif plutôt qu'un bouton de plus. */
.recherche__champ::-webkit-search-cancel-button {
  appearance: none;
  inline-size: 1.25rem;
  block-size: 1.25rem;
  background-color: var(--encre-2);
  mask: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3 3 L13 13 M13 3 L3 13" stroke="black" stroke-width="2" fill="none" stroke-linecap="round"/></svg>')
    center / contain no-repeat;
  cursor: pointer;
}

.recherche__position {
  flex: none;
  inline-size: var(--cible-min);
  display: grid;
  place-items: center;
  background: var(--terracotta);
  border: 1px solid var(--terracotta);
  border-radius: var(--rayon-bouton);
}

.recherche__position:disabled {
  opacity: 0.6;
}

/* Un réticule de visée, dessiné en CSS : pas d'icône de librairie. */
.recherche__cible {
  inline-size: 1.25rem;
  block-size: 1.25rem;
  border: 2px solid var(--fond);
  border-radius: var(--rayon-pastille);
  position: relative;
}

.recherche__cible::after {
  content: '';
  position: absolute;
  inset: 50% auto auto 50%;
  translate: -50% -50%;
  inline-size: 0.375rem;
  block-size: 0.375rem;
  background: var(--fond);
  border-radius: var(--rayon-pastille);
}

.suggestions {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  background: var(--surface);
  border: 1px solid var(--bordure);
  border-radius: var(--rayon-champ);
  overflow: hidden;
}

.suggestions__note {
  padding: var(--e-2) var(--e-3);
  font-size: var(--t-xs);
  color: var(--encre-2);
  border-block-end: 1px solid var(--ligne);
}

.suggestions__choix {
  inline-size: 100%;
  text-align: start;
  padding: var(--e-3);
  background: transparent;
  border: 0;
  border-block-end: 1px solid var(--ligne);
  font-size: var(--t-s);
  color: var(--encre);
}

.suggestions li:last-child .suggestions__choix {
  border-block-end: 0;
}

.suggestions__choix:active {
  background: var(--ligne);
}

.recherche__etat {
  font-size: var(--t-xs);
  color: var(--encre-2);
}
</style>
