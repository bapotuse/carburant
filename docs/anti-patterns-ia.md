# Anti-patterns « généré par IA » — grille de contrôle

À relire **avant** chaque page et chaque composant, et à utiliser comme grille par le sous-agent
`revue-design`. **96 signes**, classés en 9 catégories. Pour chacun : le signe, puis ce que **ce site** fait à la place.

Comment s'en servir : pour chaque point, le relecteur répond **respecté / enfreint (où, sur quelle
capture) / non applicable**. Un seul « enfreint » en catégorie A, B ou C est bloquant.

---

## A. Palette et couleurs

| # | Signe | Ce que nous faisons à la place |
|---|---|---|
| A1 | Dégradé violet → bleu (le « indigo-500 to purple-600 ») | Aplats pleins de la palette terreuse. Aucun dégradé de teinte ; au plus un dégradé de **luminosité sur une seule teinte**, et seulement pour une ombre douce. |
| A2 | Glassmorphism : panneaux translucides, `backdrop-filter: blur`, bordure blanche à 20 % | Surfaces opaques (`#ECE3D3`). Un seul effet de profondeur autorisé : la bottom sheet de la carte, qui se détache par une ombre portée douce et un bord net. |
| A3 | Lueurs néon, `box-shadow` coloré diffus, halos | Pas de lueur. La hiérarchie passe par la taille, le poids et l'espace. |
| A4 | Fond en mesh gradient / blobs flous animés | Fond crème uni, plus un grain de papier à très faible opacité (≤ 3 %). |
| A5 | Gris froids (slate, zinc, gray-50/900) sur un site censé être chaleureux | Les neutres sont **chauds** : crème `#F6F1E8`, sable `#ECE3D3`, encre `#2A2420`. Aucun gris à teinte bleue dans les tokens. |
| A6 | Texte en dégradé (`background-clip: text`) | Texte en encre. Un accent se fait en terracotta pleine, sur un mot, pas sur une phrase. |
| A7 | Mode sombre en noir pur `#000` avec texte blanc pur `#fff` | Mode sombre brun profond (base `#1A1512` environ), texte crème — jamais `#000` ni `#fff`. Contrastes mesurés comme en clair. |
| A8 | Couleurs d'accent uniquement décoratives, posées partout | Terracotta = action principale et accent éditorial. Olive = secondaire. Ardoise = données. **Une couleur par rôle**, et pas plus de deux accents par écran. |
| A9 | Couleur seule porteuse de sens (pastille de carburant sans libellé) | Encodage **redondant** systématique : forme EN 16942 (cercle essences, carré gazole, losange GPL) + libellé texte + couleur. Vérifié en simulation de daltonisme. |
| A10 | Palette de graphique par défaut de la librairie (le bleu/orange de Chart.js) | 4 ou 5 teintes terreuses définies dans les tokens, réutilisées à l'identique partout. Aucune couleur par défaut. |
| A11 | Opacité utilisée pour créer du texte secondaire (`text-white/60`) | Variantes de tokens **calculées et mesurées** (`encre-2` à 5,4:1), jamais de l'opacité sur du texte. |

## B. Typographie

| # | Signe | Ce que nous faisons à la place |
|---|---|---|
| B1 | Inter, Poppins, Montserrat, Roboto, Open Sans, Playfair Display | Écartées d'office. Paires proposées sur la planche de style, auto-hébergées via Fontsource. |
| B2 | Une seule police pour tout, en 3 graisses | Un serif de caractère pour titres et grands chiffres, un sans-serif humaniste pour le texte courant. Deux familles, pas trois. |
| B3 | Chiffres proportionnels pour les prix (les colonnes dansent) | **`font-feature-settings: "tnum"` obligatoire** sur tout prix. Une police sans chiffres tabulaires est éliminée d'office. |
| B4 | Majuscule à chaque mot des titres (« Trouvez Votre Station ») | Capitalisation française : majuscule au premier mot seulement. |
| B5 | Petit surtitre en capitales très espacées au-dessus de chaque titre | Aucun surtitre décoratif. Si une section a besoin d'être située, elle l'est par sa position et son titre. |
| B6 | Deux-points dans chaque titre (« Carburant : trouvez le meilleur prix ») | Titres sans deux-points, sauf nécessité réelle. |
| B7 | Titres en question rhétorique à répétition | Une seule question dans tout le site, celle qui est l'action : « Où faire le plein ? ». Les autres titres sont des affirmations. |
| B8 | Échelle typographique molle (16/18/20/24 px) sans hiérarchie | Échelle nette et contrastée, avec des sauts francs. Les prix sont à part, beaucoup plus grands que tout le reste. |
| B9 | Lignes de 100 caractères et plus | ≈ 65 caractères par ligne (`max-width` en `ch`). |
| B10 | Interlignage serré (1,2) sur du texte courant | 1,6 sur le texte, 1,1 sur les très grands chiffres. |
| B11 | Police < 16 px dans les champs de saisie | ≥ 16 px dans tout `input` (sinon iOS zoome tout seul au focus). |
| B12 | Points d'exclamation | Aucun, nulle part — y compris dans les états vides et les messages d'erreur. |

## C. Mise en page et composition

| # | Signe | Ce que nous faisons à la place |
|---|---|---|
| C1 | Hero centré : grand titre + sous-titre + deux boutons côte à côte | Accueil = **une seule action**, le champ de recherche, aligné à gauche, dans la zone du pouce. Pas de sous-titre explicatif, pas de second bouton de même poids. |
| C2 | Tout centré, du titre au pied de page | Alignement à gauche par défaut. Le centrage est réservé aux prix façon totem. |
| C3 | Grille de 3 cartes « fonctionnalités » (icône + titre + phrase) | Aucune grille de ce type. Les capacités du site se découvrent en s'en servant. |
| C4 | Sections toutes de même hauteur et de même marge verticale | Rythme vertical **variable et intentionnel** : la recherche est dense, les chiffres du jour respirent, l'anecdote est très aérée. |
| C5 | Bandeau de chiffres « 10k+ stations · 99,9 % · 24/7 » | Les chiffres affichés sont réels, datés et peu nombreux : nombre de stations, date de la dernière collecte, écart du jour. Jamais de « + » ni de pourcentage de fiabilité inventé. |
| C6 | Tout dans des cartes encadrées, les unes sous les autres | Sections séparées par **l'espace**, pas par des bordures. Une carte seulement quand l'objet est réellement détachable (station dans une liste). |
| C7 | Pied de page à 4 colonnes avec des liens inventés | Pied de page court et vrai : sources et licences, méthodologie, dépôt. |
| C8 | FAQ en accordéon par réflexe | Pas de FAQ. Les limites des données sont une page rédigée (« À propos / méthodologie »), pas une liste de questions. |
| C9 | Barre de navigation haute surchargée sur mobile | Navigation **basse**, 3 ou 4 entrées, dans la zone du pouce. |
| C10 | Marges identiques partout (le `p-6` universel) | Échelle d'espacement issue des tokens, avec des pas francs ; les bords d'écran gardent 16 px de gouttière, et `safe-area-inset-*` est respecté. |
| C11 | Mise en page conçue au large puis « rendue responsive » | Conçue **à 375 px d'abord**, élargie ensuite avec des container queries. |
| C12 | Le contenu principal poussé sous la ligne de flottaison par un visuel | Le champ de recherche est visible sans défiler sur iPhone SE. L'objet 3D vient **après** le LCP. |

## D. Composants

| # | Signe | Ce que nous faisons à la place |
|---|---|---|
| D1 | Librairie de composants (Vuetify, Nuxt UI, PrimeVue, shadcn-vue) ou Tailwind avec son thème par défaut | CSS natif : custom properties, `@layer`, container queries. Chaque composant dessiné pour ce site. Vérifié jusque dans l'arbre de dépendances : on refuse `@tresjs/nuxt` parce qu'il tire `@nuxt/ui`. |
| D2 | Cartes à `border-radius: 1rem` et ombre diffuse, partout | Rayons sobres et **différenciés par fonction** (champ, bouton, pastille, feuille). Au plus une ombre par écran, et douce. |
| D3 | Boutons pilule colorés pour tout | Un seul bouton plein par écran, l'action principale. Le reste est en lien ou en bouton discret. |
| D4 | Icônes de librairie dans des carrés arrondis colorés | Pictogrammes SVG dessinés pour le projet (pompe, bidon, route, borne), même épaisseur de trait, sans fond coloré. |
| D5 | Emojis en guise d'icônes, ou dans les titres | Aucun emoji dans l'interface. |
| D6 | Cibles tactiles de 32 px | ≥ 44 px pour tout élément interactif, vérifié par Playwright. |
| D7 | Champs sans `inputmode` / `autocomplete` / `enterkeyhint` | Renseignés sur chaque champ. Recherche d'adresse : `inputmode="search"`, `enterkeyhint="search"`, `autocomplete="street-address"`. |
| D8 | Focus `outline: none` ou anneau bleu par défaut du navigateur | Focus visible, dessiné à la palette, contrasté ≥ 3:1, sur **tous** les éléments focusables. |
| D9 | Bordures de champ trop claires (le token décoratif réutilisé) | Bordures de contrôle ≥ 3:1 (WCAG 1.4.11) : jamais le token `ligne`, qui est à 1,3:1 et reste décoratif. |
| D10 | Bottom sheet uniquement glissable | Glissement **plus** un bouton explicite, gestion du focus, fermeture par Échap. Utilisable sans aucun geste. |
| D11 | Jauge d'autonomie en pur décor | Vrai contrôle : `input type=range` natif habillé, valeur annoncée (« 120 km d'autonomie »), utilisable au clavier. |
| D12 | États vides, chargement et erreur génériques (« Aucun résultat ») | Rédigés un par un, avec la sortie : « Aucune station à moins de 5 km. Élargir à 10 km ? » |

## E. Iconographie et illustrations

| # | Signe | Ce que nous faisons à la place |
|---|---|---|
| E1 | Illustrations 3D génériques (personnages isométriques, blobs) | Objets 3D liés à **une donnée réelle ou une action** : jauge pilotée par l'autonomie saisie, carte en relief dont la hauteur est le prix moyen du département. |
| E2 | Claymorphism, formes pâteuses pastel | Matériaux mats ou satinés dans la palette, lumière de fin de journée, ombres douces. Ni chrome, ni néon, ni plastique. |
| E3 | Images générées par IA | Aucune. Les seules images sont des rendus de nos propres scènes 3D (replis statiques) et des schémas SVG dessinés. |
| E4 | Photos de banque d'images (la main qui tient un pistolet, le sourire en station) | Aucune photo. |
| E5 | Mélange d'épaisseurs et de styles de traits dans les pictogrammes | Une seule grille, une seule épaisseur de trait, mêmes terminaisons, pour tous les pictogrammes. |
| E6 | Favicon par défaut du framework | Favicon et image Open Graph dessinés pour le projet, version maskable incluse. |

## F. Animations et mouvement

| # | Signe | Ce que nous faisons à la place |
|---|---|---|
| F1 | Apparition en fondu vers le haut au défilement, sur chaque bloc | Aucune animation d'apparition au scroll. Le contenu est là. |
| F2 | Cartes qui se soulèvent au survol (`hover:-translate-y-1`) | Pas d'effet de survol décoratif ; de toute façon inopérant au doigt. Un retour visuel net au `:active`, c'est tout. |
| F3 | Compteurs animés partout | Le volucompteur n'est utilisé **que** pour un montant que l'utilisateur vient de demander (prix d'un plein, économie), une fois, brièvement. |
| F4 | Animations qui ignorent `prefers-reduced-motion` | Respecté partout : valeur finale affichée directement, aucun mouvement. |
| F5 | Transitions de page élaborées | Aucune transition de page. On cherche de l'essence, on ne visite pas un musée. |
| F6 | Spinner générique centré pendant 3 secondes | Chargement en **squelette** à la forme du contenu attendu, plus le micro-détail de la goutte qui se forme. |
| F7 | Parallaxe au défilement | Au plus une légère inclinaison de l'objet 3D, désactivée en `prefers-reduced-motion`. |
| F8 | Animation qui bloque le défilement vertical (rotation 3D au doigt) | `touch-action: pan-y` sur la scène 3D : rotation horizontale seulement, le défilement n'est jamais pris en otage. |

## G. Rédaction et ton

| # | Signe | Ce que nous faisons à la place |
|---|---|---|
| G1 | « Révolutionnez », « Découvrez », « Boostez », « Optimisez » | Verbes concrets : « Trouver », « Y aller », « Comparer ». |
| G2 | Tirets cadratins à répétition en incise | Phrases courtes séparées par des points. Le tiret cadratin reste rare. |
| G3 | « Pas X. Juste Y. » | Jamais. |
| G4 | Triplets d'adjectifs (« simple, rapide et efficace ») | Un adjectif, ou aucun. |
| G5 | « en quelques clics », « en un clin d'œil » | On dit le fait : « 9 826 stations, mises à jour toutes les 15 minutes ». |
| G6 | « que vous soyez… ou… » | Supprimé. |
| G7 | « Fini les… » | Supprimé. |
| G8 | Qualifier le produit d'« intelligent » ou de « propulsé par l'IA » | Jamais, nulle part, y compris dans le README et les métadonnées. |
| G9 | Majuscules marketing en milieu de phrase | Typographie française normale. |
| G10 | Voix passive et nominalisations (« la consultation des prix est permise ») | Voix active, sujet concret : « Vous voyez le prix et sa date. » |
| G11 | Humour appuyé, calembours de station (« ça carbure ! ») | Vocabulaire de station dans les intitulés (« Faire le plein », « Réserve », « Prochain arrêt »), sans jeu de mots. Au plus une pointe d'humour sec, une fois. |
| G12 | Chiffre ou anecdote sans source | Chaque fait éditorial porte sa source (URL, titre, date de consultation) stockée à côté. Au moindre doute : `docs/a-verifier.md`, et on ne publie pas. |
| G13 | « Mise à jour en temps réel » | « Dernière collecte : il y a 7 minutes. » Le prix est **toujours** affiché avec sa date de mise à jour. |
| G14 | Message d'erreur qui s'excuse sans rien dire (« Oups ! Une erreur est survenue ») | Ce qui s'est passé, et quoi faire : « Le service de géocodage ne répond pas. Réessayer, ou utiliser "Ma position". » |

## H. Structure des pages et données

| # | Signe | Ce que nous faisons à la place |
|---|---|---|
| H1 | Graphique avec grille complète, légende latérale et couleurs par défaut | Grille réduite à l'essentiel, **annotations directes sur les courbes** plutôt que légende, teintes de la palette. |
| H2 | Axes non étiquetés ou sans unité | Unité toujours présente (`€/L`, `km`, `kg CO2e`). Les noms de champs de l'API portent déjà l'unité (`prix_eur_l`). |
| H3 | Graphique dont l'axe des ordonnées ne part pas de zéro sans le dire | Si l'axe est tronqué (indispensable pour des prix), c'est signalé explicitement. |
| H4 | Moyenne calculée sur les seules lignes modifiées ce jour-là | Toutes les tendances partent de `snapshot_prix_jour` (prix **en vigueur** ce jour-là). Raison écrite dans `docs/specs/donnees.md`. |
| H5 | « Historiquement, le lundi est le moins cher » avec 3 semaines de données | Seuil minimal de données par anecdote, vérifié par requête. Sinon l'anecdote ne s'affiche pas. |
| H6 | Classement d'enseignes sur une couverture de 40 % sans le dire | Taux de couverture mesuré et **affiché** ; pas de classement sous le seuil. |
| H7 | Prix affiché sans date | Interdit. Y compris hors ligne : jamais un prix en cache sans sa date. |
| H8 | Données factices en démonstration | Aucune hors tests. La planche de style affiche des valeurs d'exemple **étiquetées comme telles**. |
| H9 | Page « À propos » vide ou absente | Page de méthodologie complète : sources, fréquence, limites (pas de nom de station, pas de DROM, seuils de fraîcheur, hypothèses du coût réel), licences et attributions. C'est la page que liront les recruteurs. |

## I. Détails techniques qui trahissent

| # | Signe | Ce que nous faisons à la place |
|---|---|---|
| I1 | Classes utilitaires par défaut visibles dans le DOM (`bg-white rounded-2xl shadow-lg p-6`) | Classes nommées par intention (`.station`, `.prix-totem`, `.feuille`), tokens en custom properties. |
| I2 | `<div>` partout, aucune sémantique | `main`, `nav`, `section`, `ul/li`, `button` vs `a` utilisés pour ce qu'ils sont. Un bouton n'est jamais un `div` cliquable. |
| I3 | Aucun état de focus clavier testé | Parcours clavier complet testé par Playwright, zéro violation axe-core sur chaque page. |
| I4 | `<img>` sans dimensions → décalage de mise en page | `width`/`height` ou `aspect-ratio` sur chaque média. Cible CLS < 0,1. |
| I5 | Polices chargées depuis un CDN tiers, avec FOIT | Auto-hébergées (Fontsource), sous-ensemble latin, `font-display: swap`, préchargement de la **seule** police des prix. |
| I6 | MapLibre dans le bundle initial | Chargé uniquement à l'ouverture de la carte. **La liste des stations fonctionne sans carte.** Budget JS initial de l'accueil ≤ ~100 Ko gzip hors carte et 3D. |
| I7 | Scène 3D qui tourne en boucle même immobile ou onglet caché | Rendu à la demande, pause quand l'onglet est caché, `devicePixelRatio` plafonné à 2, ressources libérées au démontage. |
| I8 | Pas de repli si WebGL échoue | Repli statique (AVIF/WebP **rendu depuis la scène elle-même** par script) si WebGL manque, si `prefers-reduced-motion`, si `saveData`, ou sur appareil modeste. |
| I9 | Géolocalisation demandée au chargement de la page | Demandée **au clic** sur « Ma position », avec message clair et repli sur l'adresse en cas de refus. |
| I10 | Dates et nombres au format anglais (`1.879 €`, `Nov 23`) | `Intl` en `fr-FR` côté front, helpers testés côté Python : `1,879 €`, `23 nov.`, espaces insécables. |
| I11 | Lecteur d'écran qui lit « 1,87 9 » sur un prix stylisé | Le prix façon totem expose `aria-label="1,879 euro le litre"` ; la dernière décimale réduite est purement visuelle. |
| I12 | Images en PNG/JPEG lourds | AVIF ou WebP, dimensionnées pour l'écran cible. |
