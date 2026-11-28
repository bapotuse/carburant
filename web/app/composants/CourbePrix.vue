<script setup lang="ts">
/**
 * L'historique d'un prix, en SVG, sans librairie de graphiques.
 *
 * **Lecture honnête avant tout.** Trois décisions tiennent cette courbe :
 *
 * 1. **L'axe vertical ne part pas de zéro**, sinon une variation de 1,80 à 2,10 EUR
 *    devient une ligne droite. Il est donc annoté avec ses deux bornes, pour qu'on
 *    sache de quelle amplitude on parle.
 * 2. **Le tracé est en escalier**, pas lissé : un prix change d'un coup et reste. Une
 *    courbe lissée inventerait des prix intermédiaires qui n'ont jamais été affichés.
 * 3. **L'axe horizontal va jusqu'à maintenant**, pas jusqu'au dernier changement. Le
 *    plat de droite se lit alors directement : « ce prix n'a pas bougé depuis ».
 *
 * La géométrie vit dans `composables/courbe.ts`, en fonctions pures et testées : une
 * erreur de géométrie produit une courbe qui a l'air correcte, et aucune capture
 * d'écran ne la trahit.
 */
import { tracer, type PointPrix } from '../composables/courbe'
import { dateCourte, prixLitre } from '../composables/formats'

const {
  points,
  carburant,
  titre = 'Historique du prix',
} = defineProps<{
  /** Du plus ancien au plus récent. L'appelant inverse ce que rend l'API. */
  points: PointPrix[]
  /** Code du carburant, pour la couleur. */
  carburant: string
  titre?: string
}>()

/** Repère interne du SVG. Il s'étire par `viewBox`, donc ces valeurs sont libres. */
const LARGEUR = 320
const HAUTEUR = 96

const maintenant = useState('courbe-maintenant', () => Date.now())
const tracee = computed(() => tracer(points, LARGEUR, HAUTEUR, { jusquA: maintenant.value }))

const premier = computed(() => points[0])
const dernier = computed(() => points[points.length - 1])

/**
 * Le texte que lit un lecteur d'écran à la place de la courbe.
 *
 * Une courbe est une image : sans cette phrase, elle ne dit rien à qui ne la voit pas.
 * On y met ce qu'un œil en retire — la période, l'amplitude et le prix actuel — et non
 * la liste des points, illisible à l'oreille.
 */
const resume = computed(() => {
  if (points.length === 0) return 'Aucun changement de prix enregistré sur la période.'
  if (points.length === 1) {
    return `Un seul prix connu, ${prixLitre(points[0]!.prix_eur_l)}, inchangé depuis le ${dateCourte(new Date(points[0]!.maj))}.`
  }
  const bas = prixLitre(tracee.value.bornes.bas)
  const haut = prixLitre(tracee.value.bornes.haut)
  const depuis = premier.value ? dateCourte(new Date(premier.value.maj)) : ''
  const nombre = points.length === 1 ? 'un seul changement' : `${points.length} changements`
  return `Prix du ${carburant} depuis le ${depuis} : ${nombre} de prix, entre ${bas} et ${haut} le litre. Prix actuel : ${prixLitre(dernier.value!.prix_eur_l)}.`
})
</script>

<template>
  <figure class="courbe" :style="{ '--trait': `var(--carburant-${carburant})` }">
    <figcaption class="courbe__titre">{{ titre }}</figcaption>

    <!-- Un seul point ne fait pas une courbe : le tracé serait une bande plate qui
         ressemble a une panne d'affichage. On le dit en une phrase. Constate sur la
         capture du Jalon 5, avec une base ne contenant qu'une collecte. -->
    <p v-if="points.length < 2" class="courbe__vide">
      {{
        points.length === 0
          ? 'Aucun changement de prix enregistré sur la période.'
          : `Un seul prix connu depuis le ${dateCourte(new Date(points[0]!.maj))} : ce prix n'a pas bougé depuis.`
      }}
    </p>

    <template v-else>
      <svg
        class="courbe__dessin"
        :viewBox="`0 0 ${LARGEUR} ${HAUTEUR}`"
        preserveAspectRatio="none"
        role="img"
        :aria-label="resume"
      >
        <path class="courbe__aplat" :d="tracee.aplat" />
        <path class="courbe__trait" :d="tracee.chemin" />
      </svg>

      <!-- Les bornes de l'axe, annotées directement : une courbe dont on ignore
           l'amplitude peut faire passer un centime pour un effondrement. -->
      <div class="courbe__bornes" aria-hidden="true">
        <span>{{ prixLitre(tracee.bornes.haut) }}</span>
        <span>{{ prixLitre(tracee.bornes.bas) }}</span>
      </div>
      <div class="courbe__temps">
        <span>{{ premier ? dateCourte(new Date(premier.maj)) : '' }}</span>
        <span>aujourd'hui</span>
      </div>
    </template>
  </figure>
</template>

<style scoped>
.courbe {
  margin: 0;
}

.courbe__titre {
  margin-block-end: var(--e-2);
  font-size: var(--t-s);
  font-weight: 600;
  color: var(--encre-2);
}

.courbe__vide {
  margin: 0;
  color: var(--encre-2);
  font-size: var(--t-s);
}

.courbe__dessin {
  /* `preserveAspectRatio: none` etire le repere : la hauteur est donc fixee ici, en
     unites de l'ecran, et non heritee du viewBox. */
  display: block;
  inline-size: 100%;
  block-size: 6rem;
  overflow: visible;
}

.courbe__aplat {
  fill: var(--trait);
  /* Tres transparent : l'aplat sert a lire le sens de la courbe d'un coup d'oeil, pas
     a colorer la page. */
  opacity: 0.1;
}

.courbe__trait {
  fill: none;
  stroke: var(--trait);
  /* Le trait ne doit pas s'epaissir avec l'etirement du repere. */
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
  stroke-linejoin: miter;
}

.courbe__bornes,
.courbe__temps {
  display: flex;
  justify-content: space-between;
  font-size: var(--t-xs);
  color: var(--encre-2);
  font-variant-numeric: tabular-nums;
}

.courbe__bornes {
  /* Les deux bornes se lisent de haut en bas, contre l'axe. */
  flex-direction: column;
  align-items: flex-end;
  block-size: 6rem;
  margin-block-start: -6rem;
  pointer-events: none;
}

.courbe__temps {
  margin-block-start: var(--e-1);
}
</style>
