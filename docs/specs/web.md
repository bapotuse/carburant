# Spécification — site web

## Stack
- **[corrigé 23/11/2026]** Nuxt **4.6.4** (dernière stable, publiée le 02/11/2026). **Nuxt 5 n'existe pas** : les `dist-tags` de `nuxt` s'arrêtent à `latest 4.6.4` / `4x 4.6.3` / `3x 3.21.11`. La question « évaluer Nuxt 5 » est donc close. Nuxt 3 est en fin de vie depuis le 31 juillet 2026. Vue 3 Composition API, TypeScript strict. SSR pour les pages de contenu (SEO) ; carte et 3D côté client uniquement.
- CSS natif : custom properties pour les tokens, `@layer`, container queries. Ni librairie de composants (Vuetify, Nuxt UI, PrimeVue, shadcn-vue…) ni Tailwind avec son thème par défaut : ce sont les premières sources de l'air « généré ». Chaque composant est dessiné pour ce site.
- Carte : MapLibre GL **6.19.0** + tuiles vectorielles OpenFreeMap (gratuites, sans clé). **[vérifié 23/11/2026]** `https://tiles.openfreemap.org/styles/positron` répond 200, 3,6 Ko, style v8, **55 couches**, sources `openmaptiles` + `ne2_shaded` ; glyphes et sprites servis par le même hôte (à prévoir dans la CSP, avec le `worker-src` que MapLibre exige). 55 couches rend le recoloriage Maputnik réaliste. Style recoloré à la palette, versionné dans le dépôt, attribution OpenStreetMap visible. MapLibre est lourd : il n'est chargé qu'à l'ouverture de la carte, et la liste des stations fonctionne sans carte.
- **[corrigé 23/11/2026]** 3D : **`@tresjs/core` 5.12.0 + `three` 0.187.x en direct**, et **pas** le module `@tresjs/nuxt`. Vérifié : `@tresjs/nuxt@5.10.0` est bien compatible avec Nuxt 4 (développé contre `nuxt 4.5.2`, dépend de `@nuxt/kit ^4.5.2`), **mais il déclare `@nuxt/ui ^4.11.0` en `dependencies`** — soit exactement la librairie de composants que cette spec interdit. `@tresjs/core` n'a que `vue >= 3.4` et `three >= 0.133` en peer dependencies. Chaque scène dans un composant `.client.vue`, chunk séparé, `import()` dynamique.
- Polices auto-hébergées (Fontsource), sous-ensemble latin, `font-display: swap`, préchargement de la seule police des prix.
- Client API généré depuis l'OpenAPI.

## Pages
- **Accueil** : une seule action évidente, « Où faire le plein ? ». Champ adresse (autocomplétion via l'API, anti-rebond) et bouton « Ma position », dans la zone du pouce. Résultat : liste triée, prix en héros. Puis de l'espace, les chiffres du jour et une anecdote. L'objet 3D ne retarde ni ne masque jamais la recherche : il se charge après le LCP, à l'inactivité ou quand il entre à l'écran.
- **Carte** : stations autour de moi, filtre carburant, jauge d'autonomie, bottom sheet glissable avec le classement (prix, distance, coût réel), accès à la fiche.
- **Fiche station** : prix actuels façon totem, date de mise à jour avec un indicateur de fraîcheur honnête, historique en courbe, services, horaires (ouvert en ce moment ?), bouton « Y aller ».
- **Tendances** : national et par département, comparaison des carburants, enseignes (si la couverture suffit), autoroute vs route.
- **Empreinte carbone** : calculateur « mon plein = X kg CO2e », comparaison des carburants, équivalences concrètes et sourcées.
- **Comprendre le prix** : composition d'un litre (produit, raffinage, distribution, taxes : accise et TVA), schéma clair ; chaque chiffre sourcé et daté, sources officielles en priorité.
- **À propos / méthodologie** : sources, fréquence de mise à jour, limites des données (absence de nom de station dans le flux officiel, seuils de fraîcheur, hypothèses du coût réel), licences et attributions (Licence Ouverte 2.0, Etalab 2.0 pour l'ADEME, ODbL pour OpenStreetMap, IGN), lien GitHub. Les recruteurs liront cette page : elle doit montrer la rigueur.
- **404, erreur, hors ligne** : rédigées avec soin.

## Mobile d'abord
On cherche de l'essence au volant ou à côté de sa voiture, d'une main.
- Conçu à 375 px, puis élargi vers la tablette et le bureau.
- Zone du pouce : recherche et « Ma position » en bas, navigation basse, liste en bottom sheet par-dessus la carte (accessible : gestion du focus, touche Échap, alternative sans geste de glissement).
- Cibles tactiles ≥ 44 px ; `inputmode`, `autocomplete`, `enterkeyhint` ; police ≥ 16 px dans les champs (pas de zoom involontaire sur iOS) ; `safe-area-inset-*`.
- Géolocalisation demandée au clic sur « Ma position », jamais au chargement ; message clair et repli sur l'adresse en cas de refus. Elle exige HTTPS : pour les tests sur l'iPhone de Baptiste, utilise l'environnement déployé.
- « Y aller » : Apple Plans `https://maps.apple.com/?daddr=LAT,LON`, Google Maps `https://www.google.com/maps/dir/?api=1&destination=LAT,LON`, Waze `https://waze.com/ul?ll=LAT,LON&navigate=yes`. Choix proposé, ordre adapté à la plateforme détectée.
- PWA installable (manifest, icône soignée, version maskable) ; service worker qui garde hors ligne la coquille de l'app et les dernières fiches et recherches consultées, toujours affichées avec leur date. Jamais un prix en cache sans sa date.
- Lisible en plein soleil : prix en encre sur crème (viser 7:1). Mode sombre chaleureux (brun profond, pas de noir pur) qui suit le réglage du téléphone, contrastes vérifiés aussi.
- Retour haptique avec `navigator.vibrate` seulement où il existe (absent d'iOS Safari), jamais porteur de sens.
- Budgets mesurés en profil mobile : LCP < 2,5 s, CLS < 0,1, INP < 200 ms, JS initial de l'accueil ≤ ~100 Ko gzip hors carte et 3D ; Lighthouse ≥ 90 dans les 4 catégories sur chaque page, mesuré par Lighthouse CI dans la CI. Images en AVIF ou WebP.
- Tests Playwright en émulation iPhone SE, Pixel 7 et bureau. C'est de l'émulation, dis-le ; le test sur appareil réel est fait par Baptiste sur son iPhone aux points de validation.

## Direction artistique

**Intention** : doux, chaleureux, épuré, qui respire. Un objet éditorial fait à la main par quelqu'un qui a du goût, pas un template SaaS.

### Palette
À affiner avec Baptiste. Contrastes WCAG mesurés.

| Token | Hex | Contraste sur crème / sur sable | Usage |
|---|---|---|---|
| fond | #F6F1E8 | — | fond |
| surface | #ECE3D3 | — | surfaces |
| ligne | #DDD2BF | 1,3 / 1,2 | décoratif uniquement |
| encre | #2A2420 | 13,6 / 12,0 | texte, prix |
| encre-2 | #6B6158 | 5,4 / 4,75 | texte secondaire |
| terracotta | #B85C38 | 4,0 / 3,6 | accent : grands textes, aplats, graphismes |
| olive | #6E7748 | 4,25 / 3,75 | secondaire : même usage |
| ardoise | #4A5D6E | 6,1 / 5,35 | données, liens possibles |

Conséquences :
- terracotta et olive échouent au niveau AA pour le texte courant : dérive des variantes « texte » plus sombres (≥ 4,5:1) pour les liens et petits textes ;
- texte blanc sur terracotta : 4,5:1, à la limite ; préfère l'encre ou une variante plus sombre ;
- bordures de champs et contrôles ≥ 3:1 (WCAG 1.4.11), donc jamais `ligne` ;
- la palette sombre se dérive avec les mêmes règles ;
- un test automatisé vérifie le contraste de chaque paire de tokens réellement utilisée.

Graphiques : 4 ou 5 teintes terreuses cohérentes, jamais les couleurs par défaut des librairies ; annotations directes plutôt que légendes quand c'est possible.

### Couleurs des carburants
Un token par carburant, inspiré des couleurs des pistolets en station mais réaccordé à la palette, cohérent partout (pastilles, courbes, filtres), distinguable en simulation de daltonisme et jamais seul porteur du sens (toujours accompagné d'un libellé). Piste : reprendre les formes des étiquettes européennes EN 16942 (cercle pour les essences, carré pour le gazole, losange pour le GPL) comme pastilles : un encodage redondant et authentique.

### Typographie
Un serif à caractère pour les titres et les grands chiffres, un sans-serif humaniste très lisible pour le texte. Propose 2 ou 3 paires sur la planche de style. Écarte d'office les polices sur-représentées dans les sites générés (Inter, Poppins, Montserrat, Roboto, Open Sans, Playfair Display). Une police sans chiffres tabulaires (`tnum`) est éliminée pour les prix. Échelle typographique nette, interlignage généreux, environ 65 caractères par ligne.

### Mise en page
Beaucoup d'espace, une grille claire, des sections séparées par l'espace plutôt que par des cartes encadrées. Les prix sont les héros : grands, lisibles, alignés.

### Univers carburant (subtil, jamais déguisé)
- Prix façon totem : chiffres tabulaires, trois décimales, dernière décimale plus petite (`1,87⁹`), transition douce façon afficheur quand ils changent. Pour les lecteurs d'écran : « 1,879 euro le litre ».
- Volucompteur : les montants (prix d'un plein, économie) défilent brièvement, litres et euros côte à côte ; valeur finale affichée directement si `prefers-reduced-motion`.
- Jauge E → F pour l'autonomie, avec aiguille et voyant de réserve. C'est un vrai contrôle : base `input type=range` native ou rôle `slider` ARIA complet, valeur annoncée (« 120 km d'autonomie »), utilisable au clavier.
- Textures : grain de papier très léger, marquage au sol ou lignes de route en séparateur, ticket de caisse pour le récapitulatif d'un plein (police mono, bord dentelé, total en bas).
- Micro-détails : goutte qui se forme pendant les chargements, pictogrammes SVG à trait cohérent (pompe, bidon, route, borne), identifiant de station en badge façon numéro de pompe. Pas de curseur « pistolet ».
- Vocabulaire de station dans les intitulés (« Faire le plein », « Réserve », « Prochain arrêt »), sans calembours forcés.
- Propose d'autres idées dans cet esprit et dis lesquelles tu écartes parce qu'elles basculent dans le kitsch.

### Objets 3D
De beaux objets liés à une donnée réelle ou à une action, jamais décoratifs en plein écran.
- Candidats, à proposer en description ou en croquis SVG avant de coder : pompe à essence rétro stylisée ; goutte translucide (ambre pour l'essence, doré pour le gazole) qui réagit au toucher ; jerrican ; carte de France en relief (hauteur ou couleur de chaque département = prix moyen du jour) ; jauge 3D dont l'aiguille suit l'autonomie saisie.
- Style : formes simplifiées, matériaux mats ou satinés dans la palette crème, sable, terracotta et olive, lumière douce de fin de journée, ombres portées douces. Ni chrome ni néon.
- Géométrie générée en code ou glTF compressé (Draco ou Meshopt), < 300 Ko par objet.
- Interaction : rotation au doigt horizontale uniquement (`touch-action: pan-y`, pour ne jamais bloquer le défilement) ; gyroscope seulement après un geste explicite (iOS exige `DeviceOrientationEvent.requestPermission()` déclenché par une interaction) ; légère inclinaison au scroll.
- Performance : chargement quand l'objet entre à l'écran (IntersectionObserver) et après le LCP ; `devicePixelRatio` plafonné à 2 ; rendu à la demande, aucune boucle quand rien ne bouge ; pause quand l'onglet est caché ; libération des ressources au démontage.
- Repli statique (image AVIF ou WebP rendue depuis la scène elle-même, générée par script) si WebGL est indisponible ou que le contexte échoue, si `prefers-reduced-motion` est actif, si `navigator.connection.saveData` est vrai, ou sur appareil modeste (`deviceMemory` ou `hardwareConcurrency` faibles, quand ils sont exposés). Le mode économie de batterie n'est pas détectable de façon fiable (Battery API absente de Safari et de Firefox) : n'en dépends pas.

## Anti-patterns « généré par IA »
Avant tout design, rédige `docs/anti-patterns-ia.md` : au moins 30 signes concrets, classés par catégorie (palette et couleurs, typographie, mise en page et composition, composants, iconographie et illustrations, animations, rédaction et ton, images, structure des pages, détails techniques : classes utilitaires par défaut, ombres, rayons…), chacun avec ce que ce site fera à la place. Relis-le avant chaque page ou composant ; le sous-agent `revue-design` s'en sert comme grille.

Interdits déjà connus : dégradés violet et bleu, glassmorphism, lueurs néon, fonds en mesh gradient ; emojis comme icônes ou dans les titres ; Inter partout, boutons pilule colorés partout, ombres lourdes ; grilles de 3 cartes « fonctionnalités » avec icône, titre et phrase vide ; textes marketing creux (« Révolutionnez », « Découvrez », « Boostez ») ; illustrations 3D génériques, claymorphism, images générées par IA ; tout qualifier d'« intelligent » ou de « propulsé par l'IA ».

Pour fixer le niveau d'exigence, quelques signes moins évidents (va plus loin) :
- Rédaction : tirets cadratins à répétition ; « Pas X. Juste Y. » ; triplets d'adjectifs (« simple, rapide et efficace ») ; « en quelques clics », « que vous soyez… ou… », « fini les… » ; titres en question rhétorique ; majuscule à chaque mot des titres ; deux-points dans chaque titre ; points d'exclamation.
- Mise en page : hero centré avec titre, sous-titre et deux boutons ; petit surtitre en capitales espacées au-dessus de chaque titre ; sections toutes de même hauteur et de même marge ; tout centré ; bandeau de chiffres « 10k+ » ; FAQ en accordéon par réflexe ; pied de page à 4 colonnes.
- Composants et couleur : cartes très arrondies avec ombre diffuse partout ; icônes de librairie dans des carrés arrondis colorés ; gris froids (slate, zinc) sur un site censé être chaleureux ; texte en dégradé ; mode sombre noir pur.
- Mouvement : apparition en fondu vers le haut au scroll sur chaque bloc ; cartes qui se soulèvent au survol ; compteurs animés partout.
- Données : graphiques aux couleurs, grilles et légendes par défaut de la librairie, sans annotation.

## Anecdotes
- **Calculées en direct** depuis la base, les plus intéressantes : écart du jour entre la station la moins chère et la plus chère de France sur un carburant ; département le moins cher de la semaine ; surcoût moyen d'un plein de 50 L sur autoroute ; jour de la semaine historiquement le moins cher. Chacune repose sur une requête testée et un seuil minimal de données : pas de « historiquement » avec trois semaines d'historique.
- **Éditoriales** (histoire du carburant, records, taxes), dans `data/anecdotes.yaml` : texte, source (URL, titre, date de consultation), passage de la source qui justifie le chiffre. Aucun fait inventé ; au moindre doute, `docs/a-verifier.md` pour validation par Baptiste.
- Ton : sobre, factuel, au plus une pointe d'humour sec.

## Rédaction et formats
Phrases courtes, voix active, vocabulaire concret. Formats français partout via `Intl` (`fr-FR`) : `1,879 €`, `23 nov.`, espaces insécables. États vides, de chargement et d'erreur rédigés un par un. Favicon et image Open Graph dessinés pour le projet.

## Accessibilité
WCAG 2.2 AA, navigation clavier complète, focus visible et soigné, `prefers-reduced-motion` respecté partout, aucune violation axe-core (via Playwright) sur aucune page.
