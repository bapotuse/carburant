# Faits et chiffres non confirmés

Tout ce dont on n'est pas sûr atterrit ici et **n'est pas publié** tant que ce n'est pas levé.
Colonne « Qui » : `moi` = vérifiable par une requête ou une mesure ; `Baptiste` = demande une
décision ou un accès.

| # | Point | Pourquoi c'est en doute | Comment le lever | Qui | Ouvert depuis |
|---|---|---|---|---|---|
| 1 | Le flux reste en heure locale Paris **en été** | La preuve statistique porte sur l'archive 2025 (profils janvier/juillet identiques, r = 0,9987). On n'a pas pu l'observer *en direct* un jour d'été, puisqu'on est en novembre. | Le contrôle qualité `max(maj) <= now()` tourne à chaque exécution et alerte si l'hypothèse casse. Première vraie confirmation en direct : fin mars 2027. | moi | 2026-11-23 |
| 2 | Signification exacte de `ratelimit-limit: 50` chez l'IGN | Les en-têtes renvoyés sont `ratelimit-limit: 50` **et** `x-ratelimit-limit-second: 1`. L'un est probablement le quota, l'autre la fenêtre, mais la documentation n'a pas été lue. | Lire la documentation de la Géoplateforme, ou mesurer le seuil de `429` avec prudence. En attendant : anti-rebond à 300 ms côté front, cache 24 h côté API, 5 req/s maximum sortantes. | moi | 2026-11-23 |
| 3 | Facteur de détour `s = 1,3` (distance routière ≈ géodésique × 1,3) | Valeur reprise de la spec, qui demande elle-même de la « justifier ou calibrer ». Aucune mesure faite. | Au Jalon 3 : échantillonner 200 couples (position, station) via le service d'itinéraire de la Géoplateforme, calculer le ratio médian réel, et le documenter. Jusque-là, 1,3 est affiché comme hypothèse. | moi | 2026-11-23 |
| 4 | Valeurs par défaut de `litres` et `conso_l_100km` | Nécessaires au calcul du coût réel. Aucune source officielle n'a été consultée. | Chercher une statistique publiée (volume moyen d'un plein, consommation moyenne du parc français — SDES ou Insee), la sourcer et la dater. Sinon : demander à l'utilisateur, sans valeur par défaut implicite. | moi | 2026-11-23 |
| 5 | Taux de couverture du rapprochement enseignes OpenStreetMap | La spec prévoit un rapprochement spatial avec `amenity=fuel`. Aucun test fait : on ne sait pas si on couvrira 40 % ou 90 % des 9 826 stations. | Jalon 2 : rapprochement réel, taux mesuré. **Pas de classement d'enseignes publié sous le seuil retenu**, et taux affiché dans tous les cas. | moi | 2026-11-23 |
| 6 | Composition d'un litre (produit, raffinage, distribution, accise, TVA) pour la page « Comprendre le prix » | Aucun chiffre collecté. Ce sont des données fiscales qui changent chaque année. | Sources officielles uniquement (DGEC / douanes / Légifrance pour le tarif d'accise), chaque chiffre daté et lié. Page non publiée avant. | moi | 2026-11-23 |
| 7 | Anecdotes éditoriales (histoire du carburant, records, taxes) | `data/anecdotes.yaml` est vide. | Chaque entrée porte texte, URL, titre, date de consultation et **le passage de la source qui justifie le chiffre**. Au moindre doute, l'anecdote reste ici. | moi | 2026-11-23 |
| 8 | Les 3 prix présents en face d'une rupture temporaire | Constaté dans le flux du 23/11 : 3 couples station × carburant ont à la fois un prix et une rupture temporaire déclarée. Contradiction de la source. | Journaliser ces cas à chaque collecte et suivre la fréquence. Si elle reste marginale (< 10), la rupture l'emporte sur le prix. | moi | 2026-11-23 |
| 9 | Caractéristiques réelles du VPS Oracle | `uname -m`, `free -h`, `df -h` toujours inconnus. Ils déterminent l'image PostGIS (amd64 ou arm64), les réglages Postgres et la nécessité d'un swap. **La lecture directe en ssh depuis la session est impossible** : le port 22 est refusé par le proxy sortant du conteneur. | La première exécution du workflow de déploiement les affichera dans son journal. | moi, dès que la clé de déploiement est en place | 2026-11-23 |
| 19 | Ports 80 et 443 réellement ouverts sur le VPS | Le VPS n'est pas joignable depuis la session : je ne peux pas vérifier moi-même que la *security list* du VCN et `firewalld` laissent passer. | Vérifié par le workflow de déploiement, puis par le premier certificat obtenu par Caddy. | moi + Baptiste | 2026-11-23 |
| 10 | Nom de domaine | Aucun domaine connu. Sans domaine, pas de HTTPS automatique Caddy, donc pas de géolocalisation testable sur l'iPhone. | Question 5.1 du bilan de cadrage. | Baptiste | 2026-11-23 |
| 11 | Disponibilité du nom du paquet MCP sur PyPI | Les noms candidats n'ont pas été testés : l'arbitrage du nom (question 6.1) vient d'abord. | `GET https://pypi.org/pypi/<nom>/json` → 404 = libre. À faire juste avant le Jalon 4. | moi | 2026-11-23 |
| 12 | Paire typographique définitive | Les polices écartées sont connues ; les retenues ne sont pas encore choisies. | Planche de style du Jalon 0, 2 ou 3 paires, captures mobiles, validation de Baptiste. | Baptiste | 2026-11-23 |
| 13 | Nombre réel de changements de prix par jour **en 2026** | Mesuré sur 2025 : 5 297 799 changements, soit ≈ 14 500/jour. 2026 est encore incomplète. | Recalculer sur 2026 à l'amorçage, et publier le chiffre réel dans `docs/comprendre-le-projet.md`. | moi | 2026-11-23 |
| 14 | Le parc et le rond-point du Prado restent introuvables | Sur l'index `address` de la Géoplateforme, ni le parc ni le rond-point ne ressortent — seulement des rues et des tunnels. | Tester l'index `poi` au Jalon 3. Si ça ne donne rien, le dire sur la page « À propos » : on géocode des adresses, pas des lieux-dits. | moi | 2026-11-23 |
| 15 | Comportement réel sur iOS (Safari/WebKit) | Les captures et les tests Playwright du profil `iphone-se` tournent sur **Chromium aux métriques de l'iPhone SE**, pas sur WebKit, qui n'est pas installé dans l'environnement de construction. Le zoom au focus des champs, `safe-area-inset-*`, l'absence de `navigator.vibrate` et la politique de géolocalisation ne sont donc **pas** couverts. | Installer WebKit dans la CI GitHub (`playwright install webkit`), et faire tester par Baptiste sur son iPhone aux 3 points de validation. | moi + Baptiste | 2026-11-23 |
| 16 | `typescript-eslint` et TypeScript 7 | Le projet est sur TypeScript 6.0.3 parce que `typescript-eslint@8.73.0` refuse TypeScript 7 (`>=4.8.4 <6.1.0`). Ce n'est pas la dernière version. | Suivre https://github.com/typescript-eslint/typescript-eslint/issues/10940 et remonter à la ligne 7 dès qu'elle est supportée. | moi | 2026-11-23 |
| 17 | Chiffres tabulaires de la paire typographique retenue | Vérifiés pour les six polices candidates. Une fois la paire choisie, les autres seront supprimées : il faudra reverifier que la paire retenue est bien celle testée. | Le test Playwright `les prix sont alignés au millième` tourne à chaque `make captures` et échouerait. | moi | 2026-11-23 |
| 18 | Accessibilité automatisée (axe-core) | Aucune vérification axe n'est encore branchée : elle arrive au Jalon 5, avec les vraies pages. La planche de style n'a été relue qu'à l'œil et par les tests de contraste et de cibles tactiles. | Brancher `@axe-core/playwright` au Jalon 5, zéro violation sur chaque page. | moi | 2026-11-23 |

- ~~**Let's Encrypt delivre-t-il pour un sous-domaine `sslip.io` ?**~~ **Reglé le
  25/11/2026 par la mesure** : Caddy a obtenu le certificat de
  `carburant.144-24-195-97.sslip.io` au premier essai, et le site repond en HTTPS
  depuis l'exterieur. A surveiller tout de meme au renouvellement, sslip.io etant un
  domaine partage soumis aux limites de debit de Let's Encrypt. Repli connu :
  DuckDNS, ou un vrai `.fr`.

- **[26/11/2026] `overpass-api.de` est injoignable depuis l'environnement de
  développement.** L'hôte a bien été ajouté à la politique réseau, mais chaque
  tentative meurt sur `ws_closed_mid_exchange` : le tunnel vers le proxy sortant se
  ferme avant la fin de l'échange, quatre fois sur quatre. Ce n'est ni un refus de
  politique (403/407) ni un problème de certificat. Conséquence : les enseignes
  OpenStreetMap ne peuvent pas être mises au point ici contre la vraie source.
  Elles le seront depuis le VPS, dont le conteneur a un accès réseau normal, comme
  cela a été fait pour le déploiement. À reverifier si la politique change.

### Relevés par l'audit indépendant du 26/11/2026

- **Le plancher de MAD en euros absolus est quasi inerte sur l'historique ancien.**
  Mesuré sur toute l'année 2007 : **885 prix signalés sur 4 547 129, soit 0,019 %**,
  contre les 0,4 à 2,5 % annoncés. Avec des prix autour de 1 €, le seuil de
  5 × 0,05 = 0,25 € dépasse l'amplitude nationale du jour (gazole le 15/03/2007 :
  min 0,966, max 1,200). À l'autre bout, le SP98 atteint **3,47 %** sur la base vive,
  au-dessus de la borne haute annoncée.
  → Un plancher **relatif** (de l'ordre de 2,5 % de la médiane) corrigerait les deux
  bouts. À recalibrer **par la mesure**, pas à l'intuition, avant les pages de
  tendances historiques du Jalon 5. Ne pas changer la règle sans refaire les mesures
  de `reconnaissance.md` § 1.10.
- **Deux définitions concurrentes de « prix atypique » coexistent, par conception.**
  `marts.reference_departementale` juge sur les prix frais et récents du moment (c'est
  ce que lit l'API) ; les agrégats recalculent la médiane du jour considéré (un jour de
  2019 doit se juger avec les prix de 2019). Désaccord mesuré le 24/11/2026 :
  **176 prix sur 32 148, soit 0,55 %**, changent de verdict. Le site peut donc signaler
  un prix que l'agrégat a compté comme normal. C'est défendable mais il faut le dire
  sur la page « méthodologie ».
- **Les trente premiers jours d'une période amorcée sont calculés sur un historique
  incomplet** : 2007-01-01 → 186 stations, 2007-01-02 → 1 240, 2007-02-15 → 5 853. Une
  courbe de tendance démarrerait donc sur une marche. Atténuation : charger les années
  dans l'ordre croissant, auquel cas seul le tout début de 2007 est concerné. La
  colonne `stations` permet de les repérer et le commentaire de la table le dit.
- **La Corse est absente de la dimension départementale de l'historique** : 159
  stations dont le code postal en `20xxx` ne dit pas s'il s'agit de 2A ou 2B. Elles
  comptent dans l'agrégat national mais dans aucun agrégat départemental, et ne sont
  **jamais jugées atypiques** (la règle renvoie `false` quand la médiane est inconnue).
  Le 15/03/2007 : 48 prix de gazole, moyenne 1,115 contre 1,045 ailleurs.
- **740 ruptures sans type sont invisibles en base.** Le flux publie 1 021 lignes
  `rupture` dont l'attribut `type` est vide ; data.economie met alors les champs plats
  correspondants à `null`, et l'ETL ne peut pas les voir. Aucun prix n'est concerné :
  l'effet se limite à l'information de disponibilité (« ne vend pas ce carburant »
  plutôt que « en rupture »). Cause en amont, rien à corriger chez nous.

### Ouverts par le Jalon 3 (26/11/2026)

- **Le facteur de détour de 1,3 n'est pas mesuré.** Il convertit la distance à vol
  d'oiseau en distance routière estimée, et la spec demande de le « justifier ou
  calibrer ». À 10 km à vol d'oiseau, 1,3 ajoute 6 km d'aller-retour, soit environ
  0,80 € de carburant brûlé : la valeur n'est pas neutre, un facteur trop faible
  ferait recommander des stations trop lointaines. À calibrer contre le service
  d'itinéraire de la Géoplateforme sur un échantillon de couples (position, station),
  et à noter dans `reconnaissance.md`.
- **Les valeurs par défaut du formulaire — 40 L et 7 L/100 km — ne sont pas des
  moyennes françaises mesurées.** Ce sont des valeurs pré-remplies, modifiables, et
  elles ne sont présentées nulle part comme un fait. Si on veut un jour afficher « le
  plein moyen en France », il faudra une source (SDES, ADEME) ; en attendant, ne pas
  les habiller en statistique.
- **La surconsommation de l'E85 n'est pas chiffrée.** Elle est réelle et connue — un
  véhicule parcourt moins de kilomètres avec un litre d'E85 qu'avec un litre
  d'essence, l'éthanol ayant un pouvoir calorifique plus faible — mais l'annoncer en
  pourcentage demande une source. Tant qu'elle manque, l'API dit la chose sans
  chiffre. À sourcer (ADEME, ou constructeurs) avant d'afficher un ratio sur la page
  « empreinte carbone » du Jalon 5, qui en aura besoin pour comparer à distance égale
  plutôt qu'à volume égal.
