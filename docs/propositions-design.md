# Propositions — objets 3D et détails « univers carburant »

Chaque proposition est chiffrée sur mobile. Les coûts sont des **estimations argumentées**, pas des
mesures : rien n'est encore codé. Ils seront remplacés par des mesures réelles (Lighthouse CI en
profil mobile, `performance.measure`) au Jalon 5, et ce document mis à jour.

Rappel de l'ordre de priorité de `CLAUDE.md` : la 3D est en **6e et dernière** position. Dès qu'elle
menace « trouver une station vite, d'une main » ou la performance mobile, c'est elle qu'on allège.

**Méthode de chiffrage.** « Ko transférés » = poids gzip/brotli ajouté au chargement de la page
concernée. Pour les scènes 3D on sépare le **socle Three.js** (payé une seule fois, ~160 Ko gzip
pour un import sélectif de `three` + `@tresjs/core`) du **coût propre de la scène**. Charge
CPU/GPU estimée pour un iPhone SE 2e génération (A13) et un Pixel 7 milieu de gamme.
LCP / INP : effet sur la page **où l'objet apparaît**, compte tenu du chargement différé.

---

## 1. Objets 3D

### 1.1 Recommandés

#### R1 — Jauge E → F pilotée par l'autonomie saisie ★ premier choix

Un cadran de jauge à essence : arc gradué E → F, aiguille, voyant de réserve ambré. L'aiguille suit
**la valeur réelle que l'utilisateur vient de saisir** dans le champ d'autonomie. Géométrie générée
en code (arc extrudé, aiguille = boîte biseautée, cadran = plan texturé par un canvas).

| Coût | Valeur | Justification |
|---|---|---|
| Ko transférés | **socle 160 Ko + ~6 Ko de scène** | Aucun modèle à charger : tout est généré. |
| CPU | **faible** | Rendu à la demande uniquement : une image quand l'aiguille bouge, puis plus rien. |
| GPU | **faible** | ~400 triangles, un seul matériau, pas d'ombre temps réel (ombre peinte dans la texture du cadran). |
| LCP | **aucun effet** | Elle vit sur la page carte / le sélecteur d'autonomie, pas sur l'accueil, et se charge après le LCP. |
| INP | **faible** | Le `input type=range` natif reste la source de vérité ; le rendu 3D est découplé et plafonné à un rafraîchissement par frame. |

**Pourquoi c'est le premier choix** : c'est le seul objet qui soit en même temps beau, lié à une
donnée réelle, **et utile** — il rend lisible d'un coup d'œil une valeur qu'on vient de régler au
doigt. C'est aussi le seul qui survivrait à une coupe budgétaire.

#### R2 — Carte de France en relief, hauteur = prix moyen du département

Un maillage de la France métropolitaine (+ Corse) où chaque département est extrudé à une hauteur
proportionnelle à son prix moyen du jour, et coloré dans le dégradé de luminosité de la palette.
Page **Tendances** uniquement.

| Coût | Valeur | Justification |
|---|---|---|
| Ko transférés | **socle 160 Ko + 80–120 Ko** | Contours départementaux simplifiés (Douglas-Peucker agressif, ~2 000 points au total) + extrusion en code. Un glTF Draco serait plus lourd et moins souple : on génère le maillage au vol. |
| CPU | **moyen** | L'extrusion de 96 polygones coûte ~80–150 ms une seule fois, dans un `requestIdleCallback`. |
| GPU | **faible** | ~20 000 triangles, un matériau, lumière fixe, pas d'ombre temps réel. |
| LCP | **aucun effet** | Page Tendances, chargée à l'entrée dans le viewport, après le LCP. Un repli AVIF du rendu est affiché en attendant. |
| INP | **faible** | Rotation horizontale au doigt seulement, `touch-action: pan-y`. |

**Pourquoi** : c'est la pièce qui fait « projet de data engineering » en entretien. Elle montre la
donnée agrégée, pas une décoration. Risque assumé : c'est aussi la plus coûteuse — si la mesure
dépasse le budget, on la remplace par une carte choroplèthe SVG 2D, qui dit la même chose.

#### R3 — Goutte translucide réactive au toucher

Une goutte de ~2 cm, matériau translucide satiné, ambre pour les essences, doré pour le gazole,
posée près du prix sur la **fiche station**. Au toucher, elle se déforme légèrement et revient.

| Coût | Valeur | Justification |
|---|---|---|
| Ko transférés | **socle 160 Ko + ~4 Ko** | Sphère déformée par une fonction mathématique, générée en code. |
| CPU | **faible** | Immobile au repos : zéro frame. Une courte animation (~400 ms) au toucher. |
| GPU | **moyen** | La translucidité crédible demande soit `MeshPhysicalMaterial` avec `transmission` (coûteux : une passe de rendu supplémentaire), soit une triche. **On triche** : matériau opaque satiné + un reflet peint. Coût ramené à faible. |
| LCP | **aucun effet** | Chargée à l'entrée dans le viewport. |
| INP | **faible** | L'animation ne bloque pas le fil principal. |

**Pourquoi** : petit, chaleureux, lié au carburant par sa couleur. Condition : la version
`transmission` est interdite sur mobile ; si le rendu triché n'est pas joli, on abandonne l'objet
plutôt que de payer la vraie translucidité.

### 1.2 Écartés

| Objet | Pourquoi écarté |
|---|---|
| **Pompe à essence rétro stylisée** | Le cliché exact de l'illustration 3D générée (cf. anti-pattern E1). Une pompe rétro n'est liée à **aucune donnée** : c'est un meuble. Elle est aussi la plus lourde à modéliser proprement (tuyau, pistolet, cadran, enseigne) et la plus facile à rater — une pompe approximative fait « asset gratuit ». **Remplacée par un pictogramme SVG de pompe**, dessiné à la main, qui sert d'icône. |
| **Jerrican** | Même problème, sans l'excuse de l'évocation : un bidon vert en 3D sur un site de prix de carburant est du remplissage. Et un jerrican évoque la panne sèche, pas la bonne affaire. |
| **Pistolet comme curseur de souris** | Déjà interdit par `docs/specs/web.md`. Inutilisable au doigt, casse l'accessibilité, et c'est le gadget qui date un site. |
| **Station-service complète en 3D** (auvent, îlots, voiture) | Scène de plusieurs centaines de Ko, plusieurs secondes de chargement, pour zéro information. Contraire aux priorités 2 et 3. |
| **Globe terrestre ou carte monde** | Le projet est français. Un globe serait du décor importé d'un template SaaS. |
| **Compteur kilométrique 3D qui défile en continu** | Animation permanente = batterie et CPU en continu, pour un effet qui lasse au deuxième chargement. Le volucompteur 2D (§ 2.2) fait la même chose pour 0 Ko de 3D. |

### 1.3 Garde-fous communs à toute scène 3D

Repris de `docs/specs/web.md`, à implémenter comme un **socle partagé** avant la première scène :

- Chunk séparé, `import()` dynamique, composant `.client.vue`.
- Chargement déclenché par `IntersectionObserver` **et** après le LCP (`requestIdleCallback`).
- `devicePixelRatio` plafonné à 2.
- Rendu à la demande ; aucune boucle quand rien ne bouge ; pause sur `visibilitychange`.
- Libération explicite des géométries, matériaux et textures au démontage.
- Rotation horizontale seule, `touch-action: pan-y`.
- Gyroscope **uniquement** après un geste explicite (iOS exige
  `DeviceOrientationEvent.requestPermission()` depuis une interaction).
- **Repli statique AVIF rendu depuis la scène elle-même** par un script, versionné, si : WebGL
  indisponible ou contexte perdu, `prefers-reduced-motion`, `navigator.connection.saveData`,
  `deviceMemory` ou `hardwareConcurrency` faibles.
- Pas de détection du mode économie de batterie : la Battery API est absente de Safari et de
  Firefox, on ne s'appuie pas dessus.
- **Budget dur : < 300 Ko par objet, socle inclus pour le premier.** Dépassement = on coupe.

---

## 2. Détails « univers carburant » (2D, l'essentiel de l'identité)

C'est ici que se joue le caractère du site, pour un coût très inférieur à la 3D.

### 2.1 Retenus — prix façon totem ★

Chiffres tabulaires, trois décimales, **dernière décimale plus petite et surélevée** (`1,87⁹`),
comme sur un panneau de station. Transition douce de l'ancienne à la nouvelle valeur quand le prix
change (translation verticale courte, à la façon d'un afficheur mécanique).

| Coût | Valeur |
|---|---|
| Ko transférés | **0** (CSS + un `<span>`) |
| CPU / GPU | **faible** — transform/opacity composités, pas de reflow |
| LCP | **aucun effet** ; c'est l'élément LCP de la liste, et il est en texte pur, donc rapide |
| INP | **aucun effet** |
| Accessibilité | `aria-label="1,879 euro le litre"`, la décimale réduite est purement visuelle |

**C'est le détail le plus rentable du projet** : il porte la priorité n° 1 (exactitude) et la
priorité n° 5 (finition) à la fois, pour zéro kilo-octet.

### 2.2 Retenus — volucompteur

Les **montants** (prix d'un plein, économie réalisée) défilent brièvement, litres et euros côte à
côte, comme l'afficheur d'une pompe. Uniquement pour une valeur que l'utilisateur vient de demander.

| Coût | Valeur |
|---|---|
| Ko transférés | **~1 Ko** (une petite fonction d'interpolation) |
| CPU | **faible** — ~500 ms d'animation, `requestAnimationFrame`, puis arrêt |
| GPU | **faible** |
| LCP / INP | **aucun effet** |
| Accessibilité | `aria-live="polite"` sur la **valeur finale seulement** ; valeur affichée directement si `prefers-reduced-motion` |

### 2.3 Retenus — autres

| Détail | Description | Ko | CPU/GPU | LCP | INP |
|---|---|---|---|---|---|
| **Pastilles EN 16942** | Cercle (essences), carré (gazole), losange (GPL), à la norme européenne des étiquettes à la pompe. Couleur + forme + libellé : trois encodages redondants. | ~0,5 Ko SVG inline | faible | aucun | aucun |
| **Grain de papier** | Texture de bruit très légère sur le fond (≤ 3 % d'opacité). | ~2 Ko (SVG `feTurbulence`, pas de bitmap) | faible | aucun | aucun |
| **Ticket de caisse** | Récapitulatif d'un plein : police mono, bord dentelé en CSS (`mask-image` en dents), total en bas. Sur la fiche station et le calculateur d'empreinte. | ~0 Ko (CSS) | faible | aucun | aucun |
| **Marquage au sol en séparateur** | Les séparateurs de sections sont des traits discontinus de marquage routier, pas des `<hr>` gris. | ~0 Ko (CSS `repeating-linear-gradient`) | faible | aucun | aucun |
| **Goutte de chargement** | Pendant un chargement, une goutte se forme et tombe. Remplace le spinner. | ~1 Ko SVG animé | faible | aucun | aucun |
| **Badge « numéro de pompe »** | L'identifiant officiel de la station s'affiche en badge carré, façon numéro de pompe. Rend lisible une donnée autrement opaque. | ~0 Ko | faible | aucun | aucun |
| **Pictogrammes maison** | Pompe, bidon, route, borne, poids lourd, lavage — même grille, même épaisseur de trait. Sprite SVG. | ~4 Ko pour la série | faible | aucun | aucun |
| **Vocabulaire de station** | « Faire le plein », « Réserve », « Prochain arrêt », « Au compteur ». | 0 | — | — | — |

### 2.4 Nouvelles idées, dans le même esprit

| Idée | Pourquoi elle marche | Coût |
|---|---|---|
| **Étiquette d'essai de carburant** | La fiche station reprend la forme des étiquettes grises collées sur les pistolets (code encadré + libellé en petites capitales). Authentique, et déjà réglementaire. | ~0 Ko CSS |
| **Écart au prix moyen en « centimes au litre »** | Au lieu d'un pourcentage, « 7 centimes de moins qu'en moyenne dans le Rhône ». C'est l'unité dans laquelle on pense réellement en station. | 0 |
| **« Ce que ça fait sur un plein de 50 L »** | Toute économie est aussi exprimée en euros sur un plein. C'est la seule unité qui décide d'un détour. | 0 |
| **Horaires en « ouvert jusqu'à 19 h »** | Plutôt qu'un tableau de 7 lignes : l'état maintenant, et le tableau en dépliant. | 0 |
| **Tampon « automate 24/24 »** | Un tampon encré discret sur les stations à automate, qui est l'information décisive la nuit. | ~0,3 Ko SVG |
| **Bandeau de fraîcheur en jauge, pas en pastille** | L'âge du prix est un petit segment qui se vide, avec la date en clair. Dit « frais / récent / ancien » sans code couleur seul. | ~0 Ko CSS |

### 2.5 Écartés comme kitsch

| Idée | Pourquoi écartée |
|---|---|
| **Bruit de pompe ou de moteur** | Son non sollicité : intrusif, inutilisable en voiture, et c'est la signature du site gadget. |
| **Curseur « pistolet »** | Déjà interdit. Inutilisable au doigt. |
| **Compteur d'économies cumulées « vous avez économisé 47 € »** | Faux : on ne sait pas si l'utilisateur y est allé. Un chiffre qu'on ne peut pas prouver n'a pas sa place (règle H1/G12). |
| **Fond en damier de course / drapeau à damier** | Évoque la course automobile, pas le plein. Et c'est visuellement bruyant derrière des prix. |
| **Flaque d'essence irisée en arc-en-ciel** | Jolie en photo, mais l'irisation est exactement la lueur néon interdite (A3), et elle évoque la pollution. |
| **Odomètre qui compte le nombre de visiteurs** | Bandeau de vanité (C5). |
| **Jauge qui se vide pour « dramatiser » l'autonomie** | Infantilisant, et faux : on ne connaît pas la consommation réelle. La jauge affiche ce que l'utilisateur a saisi, rien de plus. |
| **Texture métal brossé / plaque d'immatriculation** | Froid, gris, industriel : l'exact opposé de l'intention « doux, chaleureux, qui respire ». |
| **Animation de voiture qui roule vers la station** | Longue, coûteuse, et elle retarde l'information. |

---

## 3. Ce qui part en validation

Conformément à `CLAUDE.md` § « Quand t'arrêter pour Baptiste », trois points de goût :

1. **Planche de style** (Jalon 0) : paires typographiques × palette claire/sombre × prix façon
   totem × jauge × ticket de caisse, en captures mobiles.
2. **Objets 3D** (Jalon 5) : croquis SVG des trois objets recommandés, puis prototype du seul
   objet retenu.
3. **Maquettes mobiles** de l'accueil et de la carte (Jalon 5).

Le reste (détails 2D du § 2) est décidé seul, mis en œuvre, et montré en captures au bilan de
jalon — ils sont réversibles à faible coût et n'engagent pas l'architecture.
