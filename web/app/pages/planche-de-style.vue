<script setup lang="ts">
/**
 * Planche de style du Jalon 0.
 *
 * Page statique, servie uniquement pour la validation : elle ne fait partie d'aucun
 * parcours. Elle rend les trois paires typographiques candidates, la palette dans les
 * deux themes, le prix facon totem, la jauge d'autonomie et le ticket de caisse.
 *
 * Toutes les valeurs affichees sont des EXEMPLES, etiquetes comme tels. Aucune ne
 * vient de la base : le projet n'a pas encore d'ETL. Les prix choisis sont neanmoins
 * ceux reellement observes le 23/11/2026 (mediane du gazole 2,109 EUR, de l'E10
 * 1,949 EUR, de l'E85 0,869 EUR), pour que la planche montre des ordres de grandeur
 * justes plutot que des nombres inventes.
 *
 * Parametres d'URL, utilises par les captures Playwright :
 *   ?paire=A|B|C        choisit la paire typographique
 *   ?theme=clair|sombre force le theme, independamment du reglage systeme
 */
const route = useRoute()

type Paire = 'A' | 'B' | 'C'

const PAIRES: Record<Paire, { titre: string; texte: string; nom: string; note: string }> = {
  A: {
    nom: 'Petrona + Public Sans',
    titre: "'Petrona', Georgia, serif",
    texte: "'Public Sans', system-ui, sans-serif",
    note: 'Serif chaleureux, un peu condensé : laisse de la place aux grands chiffres. Chiffres tabulaires via tnum (mesuré).',
  },
  B: {
    nom: 'Newsreader + Source Sans 3',
    titre: "'Newsreader', Georgia, serif",
    texte: "'Source Sans 3', system-ui, sans-serif",
    note: 'Caractère éditorial, de presse. Chiffres tabulaires par défaut, sans réglage (mesuré).',
  },
  C: {
    nom: 'Literata + Alegreya Sans',
    titre: "'Literata', Georgia, serif",
    texte: "'Alegreya Sans', system-ui, sans-serif",
    note: 'Dessinée pour la lecture longue, très lisible en petit. Chiffres tabulaires via tnum (mesuré).',
  },
}

const paire = computed<Paire>(() => {
  const demande = String(route.query.paire ?? 'A').toUpperCase()
  return demande === 'B' || demande === 'C' ? demande : 'A'
})

const theme = computed(() => (route.query.theme === 'sombre' ? 'dark' : 'light'))

/** Les polices sont appliquées en surchargeant les tokens, sur cette page seulement. */
const polices = computed(() => ({
  '--police-titre': PAIRES[paire.value].titre,
  '--police-texte': PAIRES[paire.value].texte,
  '--police-prix': PAIRES[paire.value].titre,
}))

useHead(() => ({
  title: `Planche de style — paire ${paire.value}`,
  htmlAttrs: { 'data-theme': theme.value },
}))

/** Tokens de couleur, avec leur contraste mesuré sur fond puis sur surface. */
const NEUTRES = [
  { token: 'fond', contraste: '—', usage: 'fond de page' },
  { token: 'surface', contraste: '—', usage: 'surfaces' },
  { token: 'encre', contraste: '13,61 / 12,03', usage: 'texte, prix' },
  { token: 'encre-2', contraste: '5,37 / 4,75', usage: 'texte secondaire' },
  { token: 'ligne', contraste: '1,33 / 1,17', usage: 'décoratif uniquement' },
  { token: 'bordure', contraste: '3,47 / 3,07', usage: 'bordures de contrôle' },
]

const ACCENTS = [
  { token: 'terracotta', contraste: '4,03 / 3,57', usage: 'aplats, grands textes' },
  { token: 'terracotta-texte', contraste: '5,16 / 4,56', usage: 'liens, petits textes' },
  { token: 'olive', contraste: '4,25 / 3,75', usage: 'secondaire' },
  { token: 'olive-texte', contraste: '5,11 / 4,51', usage: 'liens secondaires' },
  { token: 'ardoise', contraste: '6,06 / 5,35', usage: 'données, liens' },
]

const CARBURANTS = [
  { code: 'sp95', contraste: '9,47 / 8,36' },
  { code: 'gplc', contraste: '8,41 / 7,43' },
  { code: 'sp98', contraste: '7,30 / 6,45' },
  { code: 'gazole', contraste: '6,39 / 5,65' },
  { code: 'e10', contraste: '5,57 / 4,92' },
  { code: 'e85', contraste: '5,13 / 4,53' },
] as const

/** Prix d'exemple : les médianes réellement mesurées le 23/11/2026. */
const PRIX_EXEMPLE = [
  { code: 'gazole', prix: 2.109 },
  { code: 'e10', prix: 1.949 },
  { code: 'sp98', prix: 2.038 },
  { code: 'e85', prix: 0.869 },
] as const

const autonomie = ref(120)

/** Le ticket utilise les formateurs testes, jamais des chaines ecrites a la main. */
const exempleTicket = {
  lignes: [
    { intitule: 'Gazole', valeur: prixLitre(2.109) },
    { intitule: 'Volume', valeur: litres(50) },
    { intitule: 'Détour', valeur: distanceKm(2.4) },
    { intitule: 'Coût du détour', valeur: euros(0.25) },
  ],
  total: { intitule: 'Total', valeur: euros(105.7) },
  mention: `Exemple — prix mis à jour le ${dateEtHeure(new Date('2026-11-23T16:00:00Z'))}`,
}
</script>

<template>
  <main id="principal" class="planche" :style="polices">
    <header class="planche__entete">
      <p class="planche__avertissement">
        Planche de style — <strong>toutes les valeurs sont des exemples</strong>, aucune ne vient de
        la base. Les prix montrés sont les médianes réellement mesurées le 23/11/2026.
      </p>
      <h1>Carburant</h1>
      <p class="planche__paire">
        Paire <strong>{{ paire }}</strong> — {{ PAIRES[paire].nom }} · thème
        {{ theme === 'dark' ? 'sombre' : 'clair' }}
      </p>
      <p class="planche__note">{{ PAIRES[paire].note }}</p>
      <nav class="planche__liens" aria-label="Changer de paire ou de thème">
        <NuxtLink
          v-for="p in ['A', 'B', 'C'] as Paire[]"
          :key="p"
          :to="{ query: { ...route.query, paire: p } }"
          >Paire {{ p }}</NuxtLink
        >
        <NuxtLink :to="{ query: { ...route.query, theme: theme === 'dark' ? 'clair' : 'sombre' } }">
          Thème {{ theme === 'dark' ? 'clair' : 'sombre' }}
        </NuxtLink>
      </nav>
    </header>

    <hr class="marquage" />

    <!-- ------------------------------------------------ prix façon totem -->
    <section>
      <h2>Le prix est le héros</h2>
      <p class="planche__legende">
        Trois décimales, chiffres tabulaires, dernier millième plus petit et surélevé. Un lecteur
        d'écran entend « 2,109 euro le litre », pas « 2,10 9 ».
      </p>
      <div class="planche__totem">
        <PrixTotem :prix-eur-l="2.109" taille="l" />
      </div>
      <ul class="planche__liste-prix">
        <li v-for="item in PRIX_EXEMPLE" :key="item.code" class="planche__ligne-prix">
          <PastilleCarburant :code="item.code" />
          <PrixTotem :prix-eur-l="item.prix" />
        </li>
      </ul>
      <p class="planche__legende">
        Les quatre prix sont alignés au millième près : c'est l'effet des chiffres tabulaires. Sans
        eux, les colonnes danseraient.
      </p>
    </section>

    <hr class="marquage" />

    <!-- ------------------------------------------------ pastilles -->
    <section>
      <h2>Carburants</h2>
      <p class="planche__legende">
        Forme de l'étiquette européenne EN 16942 : cercle pour les essences, carré pour le gazole,
        losange pour le GPL. Couleur, forme et libellé disent la même chose trois fois — la couleur
        n'est jamais seule porteuse du sens.
      </p>
      <ul class="planche__pastilles">
        <li v-for="c in CARBURANTS" :key="c.code">
          <PastilleCarburant :code="c.code" />
          <code class="planche__contraste">{{ c.contraste }}</code>
        </li>
      </ul>
    </section>

    <hr class="marquage" />

    <!-- ------------------------------------------------ jauge -->
    <section>
      <h2>Réserve</h2>
      <p class="planche__legende">
        Un vrai contrôle : <code>input type=range</code> habillé. Clavier, focus et annonce de la
        valeur sont ceux du navigateur. Le voyant s'allume sous 50 km.
      </p>
      <JaugeAutonomie v-model="autonomie" />
    </section>

    <hr class="marquage" />

    <!-- ------------------------------------------------ ticket -->
    <section>
      <h2>Au compteur</h2>
      <p class="planche__legende">
        Récapitulatif d'un plein. Bord dentelé en CSS, aucune image. Formats français avec espaces
        insécables fines.
      </p>
      <TicketPlein
        :lignes="exempleTicket.lignes"
        :total="exempleTicket.total"
        :mention="exempleTicket.mention"
      />
    </section>

    <hr class="marquage" />

    <!-- ------------------------------------------------ palette -->
    <section>
      <h2>Palette</h2>
      <p class="planche__legende">
        Contrastes WCAG mesurés, pas estimés : sur <code>--fond</code> puis sur
        <code>--surface</code>. Un test automatisé les revérifie à chaque <code>make check</code>.
      </p>

      <h3>Neutres</h3>
      <ul class="planche__palette">
        <li v-for="t in NEUTRES" :key="t.token">
          <span class="planche__echantillon" :style="{ background: `var(--${t.token})` }" />
          <code>--{{ t.token }}</code>
          <span class="planche__contraste">{{ t.contraste }}</span>
          <span class="planche__usage">{{ t.usage }}</span>
        </li>
      </ul>

      <h3>Accents</h3>
      <ul class="planche__palette">
        <li v-for="t in ACCENTS" :key="t.token">
          <span class="planche__echantillon" :style="{ background: `var(--${t.token})` }" />
          <code>--{{ t.token }}</code>
          <span class="planche__contraste">{{ t.contraste }}</span>
          <span class="planche__usage">{{ t.usage }}</span>
        </li>
      </ul>

      <p class="planche__legende">
        <strong>terracotta</strong> (4,03:1) et <strong>olive</strong> (4,25:1) échouent au niveau
        AA pour le texte courant. D'où les variantes <code>-texte</code> plus sombres, à 5,16 et
        5,11:1. Le token <code>--ligne</code> est à 1,33:1 : il reste décoratif et ne sert jamais de
        bordure de contrôle, qui doit atteindre 3:1.
      </p>
    </section>

    <hr class="marquage" />

    <!-- ------------------------------------------------ typographie -->
    <section>
      <h2>Échelle typographique</h2>
      <p class="planche__echelle" style="font-size: var(--t-2xl)">Où faire le plein ?</p>
      <p class="planche__echelle" style="font-size: var(--t-xl)">Le Prado, Marseille</p>
      <p class="planche__echelle" style="font-size: var(--t-l)">Station la moins chère</p>
      <p class="planche__echelle" style="font-size: var(--t-m)">
        Texte courant. Environ soixante-cinq caractères par ligne, interlignage généreux, voix
        active et phrases courtes. Le prix affiché l'est toujours avec sa date de mise à jour.
      </p>
      <p class="planche__echelle" style="font-size: var(--t-s); color: var(--encre-2)">
        Texte secondaire — 23 nov. à 17 h 00
      </p>
      <p class="planche__echelle" style="font-size: var(--t-xs); color: var(--encre-2)">
        Mention — prix mis à jour il y a 7 minutes
      </p>
    </section>

    <hr class="marquage" />

    <!-- ------------------------------------------------ contrôles -->
    <section>
      <h2>Contrôles</h2>
      <p class="planche__legende">
        Cibles de 44 px minimum, police à 16 px au moins dans les champs pour qu'iOS ne zoome pas,
        bordures à 3:1, focus dessiné.
      </p>
      <form class="planche__formulaire" @submit.prevent>
        <label class="planche__intitule" for="exemple-adresse">Adresse ou ville</label>
        <input
          id="exemple-adresse"
          class="champ"
          type="search"
          inputmode="search"
          enterkeyhint="search"
          autocomplete="street-address"
          placeholder="le Prado, Marseille"
        />
        <div class="planche__boutons">
          <button class="bouton bouton--principal" type="submit">Où faire le plein&nbsp;?</button>
          <button class="bouton" type="button">Ma position</button>
        </div>
      </form>
    </section>
  </main>
</template>

<style scoped>
.planche {
  max-inline-size: 42rem;
  margin-inline: auto;
  padding-block: var(--e-8) var(--e-24);
  display: grid;
  gap: var(--e-8);
}

.planche__entete {
  display: grid;
  gap: var(--e-3);
}

.planche__avertissement {
  background: var(--surface);
  border-inline-start: 3px solid var(--terracotta);
  padding: var(--e-3) var(--e-4);
  font-size: var(--t-s);
}

.planche__paire {
  font-size: var(--t-m);
  color: var(--encre-2);
}

.planche__note,
.planche__legende {
  font-size: var(--t-s);
  color: var(--encre-2);
}

.planche__liens {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-4);
  font-size: var(--t-s);
}

/* Mesuré : « Paire A » fait 42,75 px de large à cette taille de texte. La règle
   de base garantit 44 px de haut à tout lien, pas de large : il faut l'écrire. */
.planche__liens a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-inline-size: var(--cible-min);
  padding-inline: var(--e-2);
}

section {
  display: grid;
  gap: var(--e-4);
  justify-items: start;
}

h3 {
  margin-block-start: var(--e-4);
}

.planche__totem {
  padding-block: var(--e-4);
}

.planche__liste-prix,
.planche__pastilles,
.planche__palette {
  list-style: none;
  padding: 0;
  display: grid;
  gap: var(--e-3);
  inline-size: 100%;
}

.planche__ligne-prix {
  display: grid;
  grid-template-columns: 9rem 1fr;
  align-items: baseline;
  gap: var(--e-4);
  padding-block: var(--e-2);
  border-block-end: 1px solid var(--ligne);
}

.planche__pastilles li,
.planche__palette li {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  font-size: var(--t-s);
}

.planche__echantillon {
  inline-size: 2.5rem;
  block-size: 1.5rem;
  flex: none;
  border: 1px solid var(--bordure);
  border-radius: 2px;
}

.planche__contraste {
  font-family: var(--police-mono);
  font-size: var(--t-xs);
  font-variant-numeric: tabular-nums;
  color: var(--encre-2);
  margin-inline-start: auto;
}

.planche__usage {
  flex-basis: 11rem;
  color: var(--encre-2);
  font-size: var(--t-xs);
}

.planche__echelle {
  font-family: var(--police-titre);
  line-height: var(--interligne-titre);
  max-inline-size: var(--mesure);
}

.planche__echelle:nth-child(n + 4) {
  font-family: var(--police-texte);
  line-height: var(--interligne-texte);
}

.planche__formulaire {
  display: grid;
  gap: var(--e-3);
  inline-size: 100%;
}

.planche__intitule {
  font-size: var(--t-s);
  font-weight: 500;
}

.champ {
  inline-size: 100%;
  padding: var(--e-3) var(--e-4);
  background: var(--fond);
  border: 1px solid var(--bordure);
  border-radius: var(--rayon-champ);
}

.planche__boutons {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-3);
}

.bouton {
  padding: var(--e-3) var(--e-6);
  background: transparent;
  color: var(--terracotta-texte);
  border: 1px solid var(--bordure);
  border-radius: var(--rayon-bouton);
  font-weight: 500;
}

.bouton--principal {
  background: var(--terracotta);
  color: var(--fond);
  border-color: var(--terracotta);
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) .bouton--principal {
    color: #1c1714;
  }
}

:root[data-theme='dark'] .bouton--principal {
  color: #1c1714;
}
</style>
