# Reconnaissance des sources réelles

Toutes les valeurs de ce document viennent de requêtes réelles exécutées le **23/11/2026** (fin
d'après-midi, heure de Paris). Chaque section indique la commande ou l'URL utilisée pour pouvoir
rejouer la mesure. Rien ici n'est repris de mémoire.

Rappel : ce fichier fait foi pour les seuils de l'ETL. S'il contredit `docs/specs/donnees.md`,
c'est `docs/specs/donnees.md` qu'il faut corriger, en notant l'écart dans `docs/decisions.md`.

---

## 1. Flux instantané des prix (data.economie.gouv.fr)

### Accès

| Élément | Valeur constatée |
|---|---|
| Métadonnées | `GET https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2` |
| Export complet | `.../exports/{csv,json,parquet}` — fonctionne sans clé, sans pagination |
| `records_count` | **9 826** |
| `modified` | `2026-11-23T15:53:31.343000+00:00` |
| `license` | Licence Ouverte v2.0 (Etalab) |
| `timezone` déclaré | `Europe/Paris` |
| Nombre de champs | **47** |

Poids des exports (même contenu) :

| Format | Transféré (gzip) | Sur disque | Temps |
|---|---|---|---|
| parquet | 2,8 Mo | 2,8 Mo | 18 s |
| csv | 3,2 Mo | 19,6 Mo | 16 s |
| json | 4,6 Mo | 29,2 Mo | 9 s |

> **À savoir** : l'API répond en gzip/brotli. Sans `--compressed` (curl) ou `Accept-Encoding`
> géré par le client, on récupère des octets illisibles. `httpx` le gère par défaut.

### Les 47 champs

`id`, `latitude`, `longitude`, `cp`, `pop`, `adresse`, `ville`, `horaires`, `services`, `prix`,
`rupture`, `geom`, puis pour chacun des 6 carburants `<carb>_maj` (datetime) et `<carb>_prix`
(double), puis `<carb>_rupture_debut` (datetime) et `<carb>_rupture_type` (text), puis
`carburants_disponibles`, `carburants_indisponibles`, `carburants_rupture_temporaire`,
`carburants_rupture_definitive`, `horaires_automate_24_24`, `services_service`, `departement`,
`code_departement`, `region`, `code_region`, `horaires_jour`.

### Écarts par rapport à `docs/specs/donnees.md`

1. **Un champ département existe bel et bien** — `code_departement` (2 caractères) et
   `departement` (libellé), plus `code_region` / `region`. Renseignés pour 9 822 / 9 826 stations
   (4 vides). **Aucune jointure spatiale avec les contours départementaux n'est nécessaire.**
   La spec prévoyait ce champ comme incertain : il est présent et fiable.
2. **Ni nom ni enseigne** : confirmé, aucun champ de ce type. La piste OpenStreetMap reste la
   seule option.
3. **`latitude` et `longitude` sont du texte, en degrés × 100 000** (`latitude="4806100"` pour
   48,061°). C'est le format PTV de la source amont, non converti par data.economie. Le champ
   `geom` (`geo_point_2d`), lui, est en degrés décimaux corrects : **cohérence vérifiée sur les
   9 826 stations, 0 écart**. → On utilise `geom`, jamais `latitude`/`longitude`.
4. **Les dates `*_maj` sont en heure locale de Paris mais étiquetées `+00:00`** (voir § 1.4).
5. Le champ `horaires_jour` est inexploitable (valeurs du type `"Automate-24-24"`, vide à 31,9 %).
   On parse le champ `horaires` (JSON) à la place.

### 1.4 Fuseau horaire — le point le plus important

**Les horodatages du flux sont de l'heure locale Europe/Paris, servis avec un suffixe `+00:00`
mensonger.** Trois preuves indépendantes :

| Preuve | Mesure |
|---|---|
| Dates « dans le futur » | **181** valeurs `*_maj` sont postérieures à l'instant de la requête si on les lit en UTC. Le maximum est `2026-11-23T16:50:00+00:00` alors qu'il était 16h00 UTC. |
| Incohérence interne | `modified` du jeu = 15h53 UTC, mais la `maj` la plus récente = 16h50 « UTC », soit 57 min *après* la moisson. Impossible. |
| Source amont | Dans le XML de `donnees.roulez-eco.fr`, `maj` est **naïf** (sans fuseau) et vaut au plus `2026-11-23 17:00:00` quand il est 17h10 à Paris → 10 min d'ancienneté, cohérent. |

Et la preuve décisive, sur l'archive 2025 (5,3 M d'horodatages) : la distribution horaire de
janvier (CET = UTC+1) et celle de juillet (CEST = UTC+2) **se superposent**.

| Décalage appliqué à juillet | Corrélation avec janvier |
|---|---|
| −2 h | 0,022 |
| −1 h | 0,180 |
| **0 h** | **0,9987** |
| +1 h | 0,205 |
| +2 h | 0,035 |

Si le champ était en UTC, juillet serait décalé d'une heure par rapport à janvier (les gens
changent leurs prix selon l'heure de l'horloge murale, pas selon UTC). Le profil est identique :
**c'est de l'heure locale.**

**Conséquence pour l'ETL** : on parse `*_maj` en **ignorant le suffixe `+00:00`**, on localise en
`Europe/Paris` (`zoneinfo`), puis on stocke en `timestamptz`. Un contrôle qualité vérifie à chaque
exécution que `max(maj) <= now()` : si cette hypothèse devient fausse un jour (passage de la source
en UTC), l'alerte part immédiatement.

### Valeurs de `pop`

Deux valeurs seulement, des lettres : **`R` = 9 391 (95,6 %)**, **`A` = 435 (4,4 %)**.
`A` = autoroute : vérifié sur les adresses (`AUTOROUTE A10 - AIRE TOURS VAL DE LOIRE`,
`A630 ROC.PRESQU'ILE LAC COTE2`…). → `autoroute = (pop = 'A')`.

### Couverture géographique

| Mesure | Valeur |
|---|---|
| Latitude (via `geom`) | 41,391 → 51,063 |
| Longitude | −4,723 → 9,547 |
| Codes départements distincts | **97** (tous de 2 caractères) |
| Corse | `2A` = 59 stations, `2B` = 67 — codes alphanumériques présents, pas de `20` |
| **DROM / COM** | **AUCUNE station** (0 code en `97x` ou `98x`) |
| Départements les plus fournis | 13 (275), 59 (253), 62 (231), 33 (226), 69 (200) |

> **Écart avec la spec** : le contrôle qualité « coordonnées dans les emprises de la France
> métropolitaine **et des DROM** » doit porter sur **métropole + Corse uniquement** pour le flux
> instantané. L'absence des DROM est une limite à afficher sur la page « À propos ».
> (Les archives annuelles, elles, contiennent des DROM : voir § 2.)

### Remplissage des champs (sur 9 826 stations)

| Champ | Vides | Lecture |
|---|---|---|
| `id`, `cp`, `adresse`, `geom`, `pop` | 0 | toujours présents |
| `ville` | 4 | |
| `departement` / `code_departement` | 4 | |
| `prix` (bloc JSON) | 181 (1,8 %) | stations sans aucun prix |
| `services` | 669 (6,8 %) | |
| `horaires` | 1 286 (13,1 %) | |
| `gazole_prix` | 320 (3,3 %) | le gazole est quasi universel |
| `e10_prix` | 2 260 (23,0 %) | |
| `sp98_prix` | 2 244 (22,8 %) | |
| `e85_prix` | 5 915 (60,2 %) | |
| `sp95_prix` | 7 012 (71,4 %) | **le SP95 est devenu minoritaire** |
| `gplc_prix` | 8 338 (84,9 %) | |

### Structure du champ `horaires`

```json
{"@automate-24-24": "1",
 "jour": [{"@id": "1", "@nom": "Lundi", "@ferme": "",
           "horaire": {"@ouverture": "08.00", "@fermeture": "12.00"}}, …]}
```

Pièges relevés :

- **Les heures sont au format `HH.MM` avec un point**, pas `HH:MM`.
- `horaire` est **soit un objet, soit un tableau** quand la journée a deux plages
  (`[{08.00→12.00}, {14.00→19.00}]`). 26 492 jours ont un `horaire`, pour 30 034 plages.
- `horaire` peut être **absent** du jour : la station est ouverte mais sans horaire déclaré.
- `@ferme = "1"` → fermé ce jour-là (10 068 jours sur 59 780) ; `""` → ouvert.
- `@automate-24-24` vaut `"1"` (5 640) ou `""` (2 900).
- Quand `horaires` est présent, il y a **toujours exactement 7 jours** (8 540 stations × 7).
- Cas vu en vrai : `@ferme="1"` avec `horaire` `01.00 → 01.00`. Le `@ferme` l'emporte.

→ Normalisation en `jsonb` : `{"automate_24_24": bool, "jours": [{"jour": 1..7, "ferme": bool,
"plages": [["08:00","12:00"], …]}]}`.

### Services

27 valeurs distinctes, séparateur `//` dans l'API (`,` dans l'export CSV) :

| Service | Stations | | Service | Stations |
|---|---|---|---|---|
| Vente de gaz domestique (Butane, Propane) | 5 988 | | Vente d'additifs carburants | 1 771 |
| Automate CB 24/24 | 5 685 | | Location de véhicule | 1 765 |
| Station de gonflage | 5 341 | | Wifi | 1 392 |
| Boutique alimentaire | 4 197 | | Services réparation / entretien | 1 195 |
| Piste poids lourds | 4 129 | | Restauration sur place | 1 182 |
| DAB (Distributeur automatique de billets) | 3 865 | | Bornes électriques | 1 007 |
| Boutique non alimentaire | 3 504 | | Vente de fioul domestique | 871 |
| Carburant additivé | 3 350 | | Vente de pétrole lampant | 812 |
| Lavage automatique | 3 303 | | Espace bébé | 578 |
| Toilettes publiques | 2 618 | | Bar | 568 |
| Lavage manuel | 2 466 | | Douches | 463 |
| Relais colis | 2 015 | | Aire de camping-cars | 433 |
| Restauration à emporter | 1 929 | | GNV | 40 |
| Laverie | 1 836 | | | |

> À noter : `GNV` et `Bornes électriques` sont des **services**, pas des carburants du flux. On ne
> publie pas de prix pour eux.

### Ruptures

Objet `rupture` : `{@nom, @id, @debut, @fin, @type}`. `@type` ∈ {`temporaire`, `definitive`}.

| Carburant | Définitive | Temporaire |
|---|---|---|
| GPLc | 6 675 | 548 |
| SP95 | 5 431 | 664 |
| E85 | 4 543 | 480 |
| E10 | 1 496 | 404 |
| SP98 | 1 255 | 692 |
| Gazole | 11 | 261 |

- Stations avec ≥ 1 rupture temporaire : **1 826** ; définitive : **8 153**.
- Cohérence : **0** prix présent en face d'une rupture définitive, et seulement **3** en face d'une
  rupture temporaire. La source est propre sur ce point ; on journalise ces 3 cas plutôt que de
  les traiter comme la norme.

> Lecture : une rupture **définitive** signifie « cette station ne vend pas ce carburant », pas
> « panne ». C'est le mécanisme par lequel la source dit qu'un carburant est absent. Elle explique
> les taux de remplissage du § 1.6 et **ne doit pas être présentée comme une panne** sur le site.

### Prix observés — percentiles

| Carburant | n | min | p1 | p5 | p25 | **médiane** | p75 | p95 | p99 | p99,9 | max | MAD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gazole | 9 506 | 1,956 | 1,989 | 1,999 | 2,049 | **2,109** | 2,199 | 2,290 | 2,409 | 2,555 | 2,900 | 0,070 |
| sp95 | 2 814 | 1,849 | 1,911 | 1,938 | 1,979 | **1,999** | 2,064 | 2,199 | 2,320 | 2,599 | 2,710 | 0,032 |
| e10 | 7 566 | 1,790 | 1,849 | 1,869 | 1,900 | **1,949** | 1,990 | 2,121 | 2,239 | 2,349 | 2,919 | 0,041 |
| sp98 | 7 582 | 1,829 | 1,957 | 1,979 | 1,990 | **2,038** | 2,110 | 2,249 | 2,390 | 2,529 | 2,880 | 0,048 |
| e85 | 3 911 | 0,659 | 0,759 | 0,799 | 0,858 | **0,869** | 0,916 | 1,027 | 1,098 | 1,313 | 2,249 | 0,023 |
| gplc | 1 488 | 0,825 | 0,939 | 0,980 | 1,015 | **1,075** | 1,129 | 1,190 | 1,339 | 1,410 | 1,420 | 0,057 |

### Âge des prix — la fraîcheur est le vrai problème

`maj` est la date du **dernier changement de prix**, pas celle du dernier contrôle. Une station qui
ne bouge pas ses prix pendant deux semaines affiche une `maj` vieille de deux semaines sans que la
donnée soit fausse. Part des prix en dessous de chaque seuil (32 867 couples station × carburant) :

| Seuil | gazole | sp95 | e10 | sp98 | e85 | gplc | **global** |
|---|---|---|---|---|---|---|---|
| ≤ 24 h | 40,8 % | 23,8 % | 41,6 % | 36,4 % | 35,8 % | 40,2 % | **37,9 %** |
| ≤ 48 h | 42,6 % | 24,9 % | 43,2 % | 38,1 % | 36,9 % | 41,3 % | **39,5 %** |
| ≤ 72 h | 54,8 % | 35,0 % | 55,7 % | 49,9 % | 43,1 % | 46,4 % | **50,4 %** |
| ≤ 7 j | 86,4 % | 73,5 % | 88,7 % | 84,1 % | 67,7 % | 60,0 % | **81,9 %** |
| ≤ 10 j | 90,6 % | 80,0 % | 92,2 % | 88,5 % | 74,3 % | 61,8 % | **86,3 %** |
| ≤ 15 j | 96,1 % | 89,4 % | 97,1 % | 95,0 % | 84,2 % | 66,6 % | **92,7 %** |
| ≤ 30 j | 99,0 % | 95,6 % | 99,3 % | 98,5 % | 92,0 % | 75,7 % | **96,8 %** |

**Le seuil proposé par la spec (périmé au-delà de 7 jours, exclu des recherches) écarterait 18 % des
prix, et 40 % du GPLc.** C'est trop. Seuils proposés (voir question 1.1 du bilan de cadrage) :

| Classe | Seuil proposé | Couverture | Comportement |
|---|---|---|---|
| **frais** | ≤ 48 h | 39,5 % | affiché normalement |
| **récent** | 48 h → 7 j | +42,4 % (81,9 % cumulé) | affiché, mention discrète de la date |
| **ancien** | 7 j → 30 j | +14,9 % (96,8 % cumulé) | affiché avec avertissement visible, **conservé** dans les recherches, exclu des classements et des moyennes |
| **périmé** | > 30 j | 3,2 % | exclu des recherches, visible sur la fiche avec la date |

Rationnel : un prix de 10 jours est presque toujours le prix réel ; l'écarter prive l'utilisateur
d'une station qui existe. Un prix de plus de 30 jours, lui, n'a plus de valeur décisionnelle.
Dans tous les cas **la date est affichée**, jamais un prix nu.

### Prix aberrants — la règle de la spec est inutilisable telle quelle

La spec prévoit « écart à la médiane départementale du jour, en nombre de MAD ». Appliquée
littéralement, elle **signale 8 à 19 % des prix** :

| Carburant | > 3 MAD | > 5 MAD | > 6 MAD |
|---|---|---|---|
| gazole | 8,20 % | 2,44 % | 1,18 % |
| sp95 | 19,32 % | 9,66 % | 7,41 % |
| sp98 | 13,66 % | 7,22 % | 5,29 % |
| e85 | 16,88 % | 9,59 % | 7,85 % |

**Cause** : dans un département où beaucoup de stations affichent le même prix, la MAD tombe à
quelques millièmes (minimum mesuré : **0,0005 € pour le gazole en 2B**, 0,0000 € pour l'E10). Un
prix parfaitement normal se retrouve alors à 120 MAD de la médiane.

**Correction retenue : un plancher de MAD.** `suspect ⇔ |prix − médiane_dép| > k × max(MAD_dép, plancher)`

| Plancher | k | gazole | sp95 | e10 | sp98 | e85 | gplc |
|---|---|---|---|---|---|---|---|
| 0,02 € | 5 | 2,10 % | 7,27 % | 5,14 % | 6,64 % | 6,62 % | 5,56 % |
| 0,03 € | 5 | 2,10 % | 5,38 % | 4,15 % | 5,67 % | 4,14 % | 3,93 % |
| **0,05 €** | **5** | **1,16 %** | **1,85 %** | **1,79 %** | **2,49 %** | **0,64 %** | **0,41 %** |
| 0,05 € | 6 | 0,49 % | 1,00 % | 0,75 % | 1,32 % | 0,33 % | 0,14 % |

**Retenu : plancher 0,05 €, k = 5**, avec un minimum de 5 stations dans le département.

Ce que la règle attrape réellement, vérifié à la main : L'Île-d'Yeu (SP95 2,613 contre 1,99 en
Vendée), Val-d'Isère (2,599), Saint-Tropez (SP98 2,750), Cauterets (E85 2,249), Ostwald (gazole
2,876). **Ce sont pour l'essentiel de vrais prix, élevés parce que la station est sur une île, en
station de ski ou très isolée** — pas des erreurs de saisie. D'où la règle de la spec, qui est la
bonne : un prix suspect est **conservé et affiché**, simplement **exclu des classements et des
moyennes**. On ne le rejette pas.

### Bornes absolues (rejet pur et simple)

| Carburant | Bornes retenues | Observé aujourd'hui | Rejets |
|---|---|---|---|
| gazole, sp95, e10, sp98 | **[0,80 ; 3,50]** | 1,790 → 2,919 | 0 |
| e85 | **[0,35 ; 1,60]** | 0,659 → 2,249 | **4** |
| gplc | **[0,35 ; 2,00]** | 0,825 → 1,420 | 0 |

Les 4 rejets E85 sont de vraies erreurs de saisie : trois stations à `1,99` et une à `2,249` alors
que le p99,9 de l'E85 est à 1,313 — quelqu'un a saisi le prix du SP95 dans la case E85. C'est
exactement ce que les bornes par carburant doivent attraper, et ce qu'une borne commune à tous les
carburants aurait laissé passer.

---

## 2. Archives annuelles (donnees.roulez-eco.fr/opendata/annee/AAAA)

### Poids réels, année par année

| Année | zip | Année | zip | Année | zip | Année | zip |
|---|---|---|---|---|---|---|---|
| 2007 | 9,3 Mo | 2012 | 19,8 Mo | 2017 | 20,9 Mo | 2022 | 34,5 Mo |
| 2008 | 14,9 Mo | 2013 | 20,8 Mo | 2018 | 23,0 Mo | 2023 | 29,3 Mo |
| 2009 | 14,4 Mo | 2014 | 15,2 Mo | 2019 | 24,5 Mo | 2024 | 27,4 Mo |
| 2010 | 14,8 Mo | 2015 | 19,4 Mo | 2020 | 22,4 Mo | 2025 | 31,7 Mo |
| 2011 | 16,4 Mo | 2016 | 22,0 Mo | 2021 | 25,1 Mo | 2026 | 33,4 Mo (en cours) |

**Total 2007 → 2026 : 439 Mo zippés.** La spec disait « environ 400 Mo » : correct.

En revanche, 2025 seule fait **386 Mo de XML décompressé** (ratio ×12,2). Extrapolé, le total
décompressé est d'environ **5,4 Go**, et non 4,3 Go. `iterparse` en streaming est obligatoire,
comme prévu — et il n'est jamais nécessaire de décompresser sur disque : on peut lire le zip à la
volée.

### Le schéma XML change selon l'année

C'est le point le plus coûteux de l'amorçage. Caractérisé sur les 400 premières stations de chaque
année téléchargée :

| Aspect | 2007 → 2013 | 2014 | 2016 → 2017 | 2018 → 2021 | 2022 → 2026 |
|---|---|---|---|---|---|
| **Unité des prix** | millièmes | millièmes | millièmes | millièmes | **euros** |
| **Horaires** | `<ouverture debut fin saufjour>` | idem | idem | `<horaires>` + `<jour>` | `<horaires>` + `<jour>` |
| **Format de `maj`** | `espace` + microsecondes | `espace` | `T` (+ quelques `espace`) | `T` (+ quelques `espace`) | `T` (+ quelques `espace`) |

Mesures à l'appui :

- **Bascule millièmes → euros entre 2021 et 2022.** 2021 : médiane `1525` ; 2022 : médiane `1.809`.
  Il faut donc convertir pour **2007–2021** et pas pour **2022–2026**. Règle robuste qui marche
  partout : `si valeur > 20 alors valeur / 1000`. Vérifiée sur les 5 années testées.
- **Bascule `<ouverture>` → `<horaires>` entre 2017 et 2018.** 2017 a encore `<ouverture>`.
- **Les deux formats de `maj` coexistent dans un même fichier** : 2025 contient 5 297 800 dates au
  format `T` et **96** au format `espace`. Le parseur doit accepter les deux, plus les
  microsecondes des années anciennes. Ne jamais supposer un format unique.
- Les noms de services changent aussi (`Automate CB` en 2007 vs `Automate CB 24/24` aujourd'hui).
- Un élément `<fermeture type debut fin>` existe dans les archives (797 occurrences sur 400
  stations en 2025) et **pas** dans le flux instantané : il documente les fermetures de station.
- Encodage : **ISO-8859-1** déclaré, pour l'instantané comme pour les archives. À décoder
  explicitement en `latin-1` — `utf-8` échoue.
- Casse des adresses : tout en MAJUSCULES dans les archives anciennes
  (`596 AVENUE DE TREVOUX`), casse mixte dans le flux actuel (`16 rue chateaubriand`). À
  normaliser pour l'affichage.

### Qualité de l'archive 2025

| Mesure | Valeur |
|---|---|
| Stations (`<pdv>`) | **14 420** (contre 9 826 aujourd'hui : stations fermées ou renommées dans l'année) |
| Éléments `<prix>` | **5 302 458** |
| Éléments `<rupture>` | 63 442 |
| Grain unique `(station, carburant, maj)` | **5 297 799** |
| Doublons exacts du grain | **1** |
| `<prix>` malformés (ni `nom`, ni `maj`, ni `valeur`) | **4 658** |
| Changements par station | min 0, max 4 715, **moyenne 368/an** |
| Répartition par carburant | Gazole 1 520 477 · E10 1 351 304 · SP98 1 291 207 · E85 581 219 · SP95 281 659 · GPLc 271 934 |

**Le grain « un changement de prix » est quasi parfaitement unique dans la source : 1 doublon sur
5,3 millions.** Le `ON CONFLICT DO UPDATE` prévu par la spec est le bon choix, et il servira surtout
à l'idempotence des relances, pas à nettoyer la source.

**Coordonnées : les archives sont sales.** Sur 14 351 stations de 2025 :

- latitude brute de **−2 094 971** à **6 260 656** → de −20,95° (**La Réunion**) à 62,6° (au nord
  de la Norvège : aberration pure).
- longitude jusqu'à **5 529 526** → 55,3° (La Réunion, encore).
- **70 stations hors emprise métropole + Corse**, dont de vrais DROM et de vraies aberrations.
- **3 539 coordonnées non entières** (`6260655.98007`) : la règle « ×100 000 » reste bonne mais le
  champ n'est pas un entier. À parser en flottant.

→ L'amorçage doit filtrer sur l'emprise et compter les rejets, pas supposer les coordonnées bonnes.

### Volumétrie réelle en base — mesurée, pas estimée

Mesure faite dans un vrai PostgreSQL 18.7 + PostGIS (image `postgis/postgis:18-3.7`), avec le
modèle de la spec : `fact_prix(station_id bigint, carburant text, prix numeric(5,3), maj
timestamptz)`, clé primaire `(station_id, carburant, maj)`, **partitionnement mensuel sur `maj`**.

| Mesure | Valeur |
|---|---|
| Lignes chargées (2025) | **5 297 799** |
| Durée du `COPY` | **14,0 s** |
| Données (toutes partitions) | **307 Mo** |
| Index de clé primaire | **232 Mo** |
| **Total 1 an (données + PK)** | **539 Mo** |
| `dim_station` (14 281 lignes, `geography` + GiST) | 3,0 Mo |
| Coût par million de lignes | **58 Mo de données + 44 Mo d'index = 102 Mo** |

> **Index redondant détecté.** En ajoutant naïvement
> `CREATE INDEX ON fact_prix (station_id, carburant, maj DESC)` en plus de la clé primaire, on paie
> **205 Mo de plus par an pour rien** : la clé primaire `(station_id, carburant, maj)` sert déjà ces
> recherches, y compris en ordre décroissant (PostgreSQL parcourt un index en arrière). Mesuré :
> index total 438 Mo avec, 232 Mo sans. **À ne pas créer.**

Lignes `<prix>` par année (comptage réel) :

| Année | Lignes | Année | Lignes | Année | Lignes |
|---|---|---|---|---|---|
| 2007 | 866 445 | 2016 | 3 891 588 | 2022 | 5 044 596 |
| 2008 | 1 421 554 | 2017 | 3 659 483 | 2023 | 4 683 353 |
| 2010 | 1 443 536 | 2018 | 3 882 564 | 2024 | 4 587 613 |
| 2012 | 1 903 238 | 2020 | 3 860 225 | 2025 | 5 297 800 |
| 2013 | 2 150 589 | 2021 | 4 283 692 | 2026 (partiel) | 4 871 919 |
| 2014 | 2 197 948 | | | | |

(2009, 2011, 2015 et 2019 interpolés : ≈ 10,0 M au total.)

**Projection de volume :**

| Périmètre | Lignes | Taille en base (données + PK) |
|---|---|---|
| 1 an (2025) | 5,3 M | **0,54 Go** |
| 3 ans (2023–2025) | 14,6 M | **1,5 Go** |
| **2007 → aujourd'hui** | **≈ 64 M** | **≈ 6,5 Go** |

Avec l'index redondant, l'historique complet pèserait ≈ 9 Go. Sans, 6,5 Go — ce qui tient sans
difficulté sur le stockage du Free Tier Oracle. **Recommandation : amorcer l'historique complet
2007 → aujourd'hui en détail**, sans agrégation par département pour les années anciennes. La spec
proposait des agrégats pour les vieilles années « selon le volume mesuré » : le volume mesuré ne
le justifie pas, et le détail complet permet l'anecdote « jour de la semaine historiquement le moins
cher » sur 19 ans.

Durée estimée de l'amorçage complet : 64 M lignes à ≈ 380 000 lignes/s en `COPY` → **≈ 3 min de
chargement**, plus ≈ 15 min de parsing XML (37 s par année de 5 M de lignes, mesuré) et le
téléchargement de 439 Mo. **Moins d'une demi-heure au total.**

### Piège de partitionnement découvert à la mesure

En partitionnant `fact_prix` sur `maj timestamptz` avec des bornes `2025-01-01` → `2025-02-01`
*écrites sans fuseau*, **3 612 lignes sont tombées dans la partition `DEFAULT`**. Ce ne sont pas des
anomalies : ce sont les changements de prix du **1er janvier 2025 entre 00h00 et 00h58 heure de
Paris**, soit `2024-12-31 23:00 → 23:58 UTC`. Les bornes de partition sont interprétées en UTC.

→ Les bornes doivent être calculées en UTC, et l'amorçage doit créer **la partition du mois
précédant** le premier mois de données. La règle de la spec (« partition DEFAULT doit rester vide,
alerte sinon ») est bonne et aurait détecté le problème en production ; elle le détecte ici.

---

## 3. Facteurs d'émission — ADEME

### Écart majeur : l'API a changé de plateforme

`docs/specs/donnees.md` suppose une API Opendatasoft sur le portail ADEME. **Ce n'est plus le cas.**

```
GET https://data.ademe.fr/api/explore/v2.1/catalog/datasets
→ HTTP 410 "Cette couche de compatibilité pour la version d'API précédente ne supporte pas cette requête."
```

Le portail tourne désormais sur **Data Fair**. La bonne base est :

```
https://data.ademe.fr/data-fair/api/v1/datasets/base-carboner
```

| Métadonnée | Valeur |
|---|---|
| `id` / `slug` | `base-carboner` |
| Titre | Base carbone® |
| Lignes | **18 616** |
| `updatedAt` | **2026-06-30T10:17:08.470Z** |
| Licence | Licence Ouverte / Open Licence |
| Producteur | ADEME |

Points d'API utiles : `/lines` (avec `qs` en syntaxe Lucene, `size`, `select`, `after` pour la
pagination) et `/values/<champ>` pour les valeurs distinctes. Aucune clé requise.

Deux pièges :

1. **Chaque élément apparaît en plusieurs lignes** : `Type_Ligne = "Elément"` (la valeur totale) et
   `Type_Ligne = "Poste"` (la décomposition amont / combustion). Sans filtrer sur `Type_Ligne`, on
   compte les facteurs en double.
2. L'unité s'écrit **`kgCO2e/litre`** dans les données (la liste des valeurs distinctes affiche
   aussi `kgCO2e/Litre`) ; il y a 194 lignes et **92 éléments** dans cette unité.
   `Nom_frontière_français` est vide pour tous les carburants routiers : le périmètre est porté par
   les lignes `Poste`.

### Mapping carburant → élément (France continentale, « Valide générique », kgCO2e/litre)

| Carburant du flux | Identifiant | `Nom_base_français` | `Nom_attribut_français` | Valeur | Combustion | Amont | Modifié le | Validité | Incertitude |
|---|---|---|---|---|---|---|---|---|---|
| **gazole** | **25775** | Gazole routier | B7 | **3,1** | 2,49 | 0,609 | 2021-06-18 | déc-20 | 10 % |
| **sp95** | **25763** | Essence | Supercarburant sans plomb (95, 95-E10, 98) | **2,69** | 2,20 | 0,491 | 2021-06-18 | déc-20 | 10 % |
| **sp98** | **25763** | Essence | Supercarburant sans plomb (95, 95-E10, 98) | **2,69** | 2,20 | 0,491 | 2021-06-18 | déc-20 | 10 % |
| **e10** | **13988** | Essence | E10 | **2,69** | 2,19 | 0,502 | 2021-06-18 | déc-20 | 10 % |
| **e85** | **25766** | Essence | E85 | **1,11** | 0,366 | 0,743 | 2021-06-18 | déc-20 | 10 % |
| **gplc** | **14031** | GPL pour véhicule routier | — | **1,86** | 1,60 | 0,257 | 2014-10-20 | déc-20 | 5 % |

Catégorie commune : `Combustibles > Fossiles > Liquides > Usage sources mobiles > Usage routier`.
Contributeur : ADEME.

**La spec avait raison** : un seul élément (25763) couvre SP95, E10 **et** SP98 — son libellé le dit
littéralement. Nous retenons tout de même **13988 pour l'E10**, plus spécifique, et qui donne la
même valeur de 2,69. Le choix est documenté pour pouvoir être défendu en entretien.

**Contrôle de cohérence avec les ordres de grandeur de la spec** (écart autorisé : 20 %) :

| Carburant | Ordre de grandeur spec | Mesuré | Écart |
|---|---|---|---|
| essence | 2,7 | 2,69 | 0,4 % |
| gazole | 3,1 | 3,10 | 0 % |
| E85 | 1,1 | 1,11 | 0,9 % |
| GPL | 1,9 | 1,86 | 2,1 % |

Tous conformes : l'unité est bien le **kgCO2e par litre**, pas par kg ni par MJ.
`total = combustion + amont` vérifié (3,1 = 2,49 + 0,609).

**Pas de champ « version de la base »** dans l'API. On stocke à sa place `updatedAt` du jeu
(2026-06-30), `Date_de_modification` de l'élément et `Période_de_validité`, comme le prévoit
`ref_facteur_emission`.

À noter : l'E85 a un profil inversé (combustion 0,366 ; amont 0,743) — l'essentiel de son empreinte
est en amont, parce que le carbone brûlé est biogénique. C'est une bonne anecdote sourcée pour la
page empreinte carbone.

---

## 4. Géocodage — Géoplateforme IGN

`https://data.geopf.fr/geocodage/search` répond en GeoJSON, sans clé.
Autocomplétion : `https://data.geopf.fr/geocodage/completion` (`text`, `type`, `maximumResponses`).

En-têtes de débit renvoyés : **`ratelimit-limit: 50`** et `x-ratelimit-limit-second: 1`.
CORS totalement ouvert (`access-control-allow-origin: *`) — un appel direct depuis le navigateur
serait possible, mais on garde le proxy `/v1/geocode` avec cache, pour ne pas dépendre du quota
partagé et pour pouvoir limiter à la France.

### Les quatre requêtes demandées

**« le Prado, Marseille »** — ambiguïté réelle, aucun candidat évident :

| Score | Type | Libellé | Coordonnées |
|---|---|---|---|
| 0,608 | street | Allée prado bleu 13008 Marseille | 5,374039 / 43,266290 |
| 0,595 | street | Avenue du prado 13008 Marseille | 5,386189 / 43,272573 |
| 0,586 | street | Avenue du prado 13006 Marseille | 5,384967 / 43,283721 |
| 0,483 | locality | Tunnel prado sud--argile 13010 Marseille | 5,395304 / 43,281785 |
| 0,468 | locality | Tunnel prado carenage 13006 Marseille | 5,379430 / 43,285795 |

**« Prado Marseille »** — scores plus hauts mais **plus serrés**, donc plus ambigu :
Avenue du prado 13008 (0,708), Avenue du prado 13006 (0,699), Voie de liaison herriot--prado
(0,686), Tunnel prado sud--prado (0,686), Tunnel carenage prado (0,683). **Cinq candidats en
0,025 point.**

**« 13008 »** — un gagnant net : `municipality` « Marseille 8e Arrondissement » à **0,865**, le
suivant à 0,708.

**« 40 avenue du Prado, 13006 Marseille »** — sans ambiguïté : `housenumber` à **0,972**, le suivant
à 0,455.

### Conséquences pour l'API et le MCP

1. L'avenue du Prado **traverse deux arrondissements** (13006 et 13008) et apparaît deux fois avec
   des scores quasi identiques : 1,2 km séparent les deux points. Il n'existe pas de « bon »
   candidat à deviner.
2. Les tunnels et voies de liaison polluent les résultats. **Filtrer sur `type`** : garder
   `housenumber`, `street`, `municipality`, `locality`, et déprioriser les `locality` dont le
   libellé commence par `Tunnel`.
3. **Règle d'ambiguïté chiffrée, dérivée de ces mesures** : renvoyer les candidats au lieu de
   choisir si `score_1 < 0,80` **ou** si `score_1 − score_2 < 0,05`.
   – « 40 avenue du Prado… » → 0,972 et écart 0,517 → **réponse directe**.
   – « 13008 » → 0,865 et écart 0,157 → **réponse directe**.
   – « le Prado, Marseille » → 0,608 → **demande de précision**.
   – « Prado Marseille » → écart 0,009 → **demande de précision**.
   Ce qui correspond exactement au comportement voulu par `docs/specs/api-mcp.md`.
4. Le parc du Prado et le rond-point du Prado ne ressortent pas du tout sur l'index `address` : il
   faudra interroger aussi l'index `poi` pour les lieux-dits, ou accepter de ne proposer que des
   rues.

---

## 5. Versions et compatibilités (relevées le 23/11/2026)

### Front

| Paquet | Dernière version | Publiée le | Retenu |
|---|---|---|---|
| `nuxt` | **4.6.4** | 2026-11-02 | **4.6.4** |
| `vue` | 3.5.46 | 2026-11-20 | 3.5.x |
| `maplibre-gl` | **6.19.0** | 2026-11-17 | 6.19.0 |
| `@tresjs/core` | **5.12.0** | 2026-11-17 | 5.12.0 |
| `@tresjs/nuxt` | 5.10.0 | 2026-11-17 | **écarté, voir ci-dessous** |
| `three` | 0.187.0 | 2026-10-30 | 0.187.x |
| `@vite-pwa/nuxt` | **2.0.4** | 2026-11-22 | 2.0.4 |
| `vite` | 8.3.8 | 2026-11-11 | via Nuxt |
| `typescript` | 7.0.2 | 2026-07-08 | 7.0.x |
| `vue-tsc` | 3.3.14 | 2026-10-29 | 3.3.x |
| `eslint` | 10.15.0 | 2026-11-13 | 10.x |
| `prettier` | 3.10.1 | 2026-11-12 | 3.x |
| `vitest` | 5.1.1 | 2026-11-18 | 5.x |
| `@playwright/test` | 1.65.1 | 2026-11-13 | 1.65.x |

**Nuxt 5 n'existe pas.** Les `dist-tags` de `nuxt` sont : `latest 4.6.4`, `4x 4.6.3`,
`3x 3.21.11`, `2x 2.18.1`, `1x 1.4.5`, plus des `alpha`/`rc` qui pointent sur du 4.0.0.
La question « évaluer Nuxt 5 s'il est stable » posée par la spec est donc sans objet aujourd'hui.

**TresJS est compatible avec Nuxt 4, mais on n'utilisera pas son module Nuxt.**
`@tresjs/nuxt@5.10.0` est développé contre `nuxt 4.5.2` et dépend de `@nuxt/kit ^4.5.2` : la
compatibilité est établie. **Mais il déclare `@nuxt/ui ^4.11.0` en `dependencies`** — pas en
`devDependencies`. Or `docs/specs/web.md` interdit explicitement les librairies de composants,
Nuxt UI nommément. Installer le module ferait entrer dans l'arbre de dépendances exactement ce
qu'on veut éviter, et alourdirait l'installation.
→ **Décision : `@tresjs/core` + `three` en direct**, dans un composant `.client.vue` importé
dynamiquement. On garde l'API déclarative de TresJS (lisible en entretien) sans le module Nuxt.
Noté dans `docs/decisions.md`.

### Python

| Paquet | Dernière version | `requires_python` | Classifiers |
|---|---|---|---|
| `mcp` (SDK officiel) | **2.3.0** (2026-10-02) | ≥ 3.10 | jusqu'à **3.14** |
| `fastapi` | 0.165.0 | ≥ 3.11 | jusqu'à 3.15 |
| `pydantic` | 2.14.4 | ≥ 3.10 | jusqu'à 3.15 |
| `sqlalchemy` | 2.1.9 | ≥ 3.11 | jusqu'à 3.15 |
| `psycopg` | 3.3.9 | ≥ 3.10 | jusqu'à 3.15 |
| `httpx` | 0.28.1 | ≥ 3.8 | — |
| `uv` | 0.13.9 | — | — |
| `ruff` | 0.17.6 | — | — |
| `mypy` | 2.4.1 | ≥ 3.10 | — |
| `pytest` | 9.2.0 | ≥ 3.10 | — |
| `alembic` | 1.20.1 | ≥ 3.10 | — |
| `prefect` | 3.9.4 | ≥ 3.11, **< 3.16** | jusqu'à 3.15 |
| `respx` | 0.23.1 | ≥ 3.8 | — |
| `hypothesis` | 6.170.17 | ≥ 3.11 | jusqu'à 3.15 |

Versions de Python publiées en image officielle : 3.12.16, 3.13.18, **3.14.10**, 3.15.2.

**Le SDK `mcp` 2.3.0 est le facteur limitant : ses classifiers s'arrêtent à 3.14.**
→ **Python 3.14** retenu. C'est « la dernière version stable supportée par toutes les dépendances »
au sens de `CLAUDE.md`. Le SDK est bien sur la **ligne 2.x** annoncée par la spec.

### Node

`node:lts` et `node:26` ont **le même digest** (`sha256:e18c3ccd…`, poussé le 2026-11-11) :
**Node 26 est la LTS active**. Node 24 existe encore (digest différent) mais n'est plus la LTS.
Architectures de `node:26` : amd64, arm64, ppc64le, s390x.
→ **Node 26** retenu.

### Image PostGIS — le problème arm64 est réel et toujours d'actualité

| Image | amd64 | arm64 | Dernière poussée |
|---|---|---|---|
| `postgis/postgis:18-3.7` | ✅ | ❌ | 2026-11-23 |
| `postgis/postgis:17-3.7` | ✅ | ❌ | 2026-11-23 |
| `postgis/postgis:latest` | ✅ | ❌ | 2026-11-23 |
| `postgis/postgis:18-3.6` | ✅ | ❌ | 2026-10-26 |
| **`imresamu/postgis:18-3.6-alpine`** | ✅ | **✅** | **2026-11-23** |
| **`imresamu/postgis:17-3.6-alpine`** | ✅ | **✅** | **2026-11-23** |
| `imresamu/postgis:18-3.6` (debian) | ✅ | ✅ | 2026-02-09 |
| `postgres:18` (officiel, sans PostGIS) | ✅ | ✅ | — |

**Vérifié sur les tags poussés le jour même : `postgis/postgis` n'a toujours aucune image arm64.**
L'avertissement de `docs/specs/infra.md` est confirmé.

`imresamu/postgis` est le dépôt multi-architecture maintenu par le mainteneur des images PostGIS
officielles ; ses variantes alpine sont reconstruites quotidiennement.

→ **Décision** : `postgis/postgis:18-3.7` en local (amd64), et le choix de l'image de production
se fait **après avoir lu `uname -m` sur le VPS**. Si le VPS est aarch64 (Ampere A1) :
`imresamu/postgis:18-3.6-alpine`. La version de PostGIS diffère alors légèrement entre
développement et production (3.7 vs 3.6) : à aligner sur 3.6 partout pour éviter toute surprise.
Décision finale notée dans `docs/decisions.md` au Jalon 1, après lecture du VPS.

### Validation du socle, mesurée

Fait tourner pour de vrai pendant cette reconnaissance :

| Vérification | Résultat |
|---|---|
| `postgis/postgis:18-3.7` démarre | ✅ PostgreSQL **18.7** |
| `CREATE EXTENSION postgis` | ✅ |
| `COPY` de 5 297 799 lignes dans une table partitionnée | ✅ **14,0 s** |
| Création de 14 partitions mensuelles + DEFAULT | ✅ |
| `geography(Point,4326)` + index GiST sur 14 281 stations | ✅ 43 ms |
| Requête type `/v1/stations/proches` : `ST_DWithin` 10 km autour du Prado + dernier prix par station via `LATERAL` | ✅ **13,7 ms** pour 116 stations |

La cible « p95 < 300 ms sur le VPS pour `/stations/proches` » est donc confortable : 13,7 ms sur
cette machine (4 vCPU, 15 Go). Le VPS sera plus lent, mais l'ordre de grandeur laisse une marge
d'un facteur 20.

---

## 6. Tuiles de carte — OpenFreeMap

`https://tiles.openfreemap.org/styles/positron` répond 200, **3 583 octets**, sans clé.

| Élément | Valeur |
|---|---|
| Version de style | 8 |
| Sources | `openmaptiles`, `ne2_shaded` |
| Couches | **55** |
| Glyphes | `https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf` |
| Sprites | `https://tiles.openfreemap.org/sprites/ofm_f384/ofm` |

55 couches, c'est peu : le recoloriage à la palette dans Maputnik est réaliste. Les polices et les
sprites sont servis par le même hôte — à prévoir dans la CSP de Caddy, avec le `worker-src` que
MapLibre exige.

---

## 7. Récapitulatif des écarts avec les specs

| # | Spec concernée | Ce que dit la spec | Ce qu'on a constaté | Action |
|---|---|---|---|---|
| 1 | donnees.md | Champ département « s'il existe, sinon jointure spatiale » | `code_departement` présent et fiable (4 vides / 9 826) | Pas de jointure spatiale. Spec à corriger. |
| 2 | donnees.md | Dates à vérifier : locales ou UTC | **Heure locale Paris étiquetée `+00:00`** par data.economie | Parser en ignorant le suffixe, localiser en Europe/Paris. Contrôle `max(maj) <= now()`. |
| 3 | donnees.md | Coordonnées « multipliées » possibles dans les archives | Vrai dans les archives **et** dans les champs `latitude`/`longitude` du flux v2 | Utiliser `geom` pour le flux ; `/1e5` + filtre d'emprise pour les archives. |
| 4 | donnees.md | Règle relative en nombre de MAD | Signale 8–19 % des prix : MAD départementale parfois nulle | **Plancher de MAD à 0,05 €, k = 5.** |
| 5 | donnees.md | Périmé au-delà de 7 jours, exclu des recherches | Écarterait 18 % des prix et 40 % du GPLc | 4 classes : frais ≤ 48 h, récent ≤ 7 j, ancien ≤ 30 j, périmé > 30 j. |
| 6 | donnees.md | DROM à gérer (Corse 2A/2B, DROM) | **Aucun DROM dans le flux** ; Corse présente ; DROM présents dans les archives | Contrôle d'emprise sur métropole + Corse ; limite documentée sur « À propos ». |
| 7 | donnees.md | API ADEME sur le portail open data (Opendatasoft) | **HTTP 410**, portail migré sur **Data Fair** | Nouvelle URL `data-fair/api/v1/datasets/base-carboner`. Spec à corriger. |
| 8 | donnees.md | « ~4,3 Go de XML au total » | **≈ 5,4 Go** (439 Mo zippés, confirmé) | Chiffre corrigé. |
| 9 | donnees.md | Prix en millièmes « selon les années » | Millièmes **2007–2021**, euros **2022–2026** | Règle `valeur > 20 → /1000`. |
| 10 | donnees.md | Détail récent + agrégats pour les années anciennes | Historique complet = **6,5 Go**, chargeable en < 30 min | **Historique complet en détail**, pas d'agrégats dégradés. |
| 11 | donnees.md | Partition DEFAULT doit rester vide | Bornes interprétées en UTC → la 1re heure de chaque mois local déborde | Bornes calculées en UTC + partition du mois précédent. |
| 12 | web.md | « Nuxt 4.x, évaluer Nuxt 5 s'il est stable » | **Nuxt 5 n'existe pas** | Nuxt 4.6.4. Question close. |
| 13 | web.md | TresJS « s'il est compatible » | Compatible Nuxt 4, **mais `@tresjs/nuxt` dépend de `@nuxt/ui`**, interdit par la spec | `@tresjs/core` + `three` en direct, sans le module Nuxt. |
| 14 | infra.md | PostGIS arm64 « à vérifier » | Toujours **amd64 seulement** sur `postgis/postgis` | `imresamu/postgis` en arm64 si le VPS est aarch64. |
| 15 | donnees.md | — | **4 658 `<prix>` malformés** par archive annuelle ; `<fermeture>` absent du flux ; encodage **ISO-8859-1** ; deux formats de `maj` **dans le même fichier** | Parseur tolérant, rejets comptés. |

## 6. Enseignes — OpenStreetMap (reconnaissance du 26/11/2026)

### Le constat qui change le plan : OSM porte l'identifiant officiel

La spécification prévoyait un **rapprochement spatial** PostGIS entre nos stations et les points
`amenity=fuel` d'OpenStreetMap. Mesure faite : ce n'est pas nécessaire pour la grande majorité
des stations.

```
[out:json][timeout:600];
area["ISO3166-1"="FR"][admin_level=2]->.fr;
nwr["amenity"="fuel"](area.fr);
out center tags;
```

**12 610 éléments** (8 119 `node`, 4 478 `way`, 13 `relation`), 7,7 Mo de JSON, réponse en 103 s.
`out center` donne une position à tous : **0 élément sans position exploitable.**

| Tag | Éléments | Part |
|---|---|---|
| `name` | 10 853 | **86,1 %** |
| `brand` | 10 833 | **85,9 %** |
| `brand:wikidata` | 10 205 | **80,9 %** |
| **`ref:FR:prix-carburants`** | **10 146** | **80,5 %** |
| `operator` | 4 385 | 34,8 % |

**`ref:FR:prix-carburants` est l'identifiant officiel du flux que nous collectons déjà** (par
exemple `"21320007"`). Pour 80,5 % des stations OSM, le rapprochement est donc une **jointure sur
clé**, pas une devinette géographique. Beaucoup portent d'ailleurs un tag `source` du type
« Ministère de l'Economie, de l'Industrie et du Numérique - 03/2020 » : OSM a importé la même
source officielle que nous.

→ **Stratégie retenue** : jointure sur `ref:FR:prix-carburants` d'abord, score 1,0 ;
rapprochement spatial seulement pour le reste, avec un score dégradé selon la distance. Le taux
de correspondance final est mesuré et affiché, et sans enseigne une station s'affiche par son
adresse.

### `brand:wikidata` unifie les variantes de marque

C'est le second apport, et il résout un problème que la spec n'avait pas vu venir. Les libellés
`brand` éclatent une même enseigne en plusieurs écritures :

| `brand` | Éléments |
|---|---|
| TotalEnergies | 1 209 |
| Total | 1 078 |
| Total Access | 405 |

…alors que `brand:wikidata = Q154037` en compte **2 674**, soit la somme à quelques unités près.
Un classement d'enseignes construit sur le libellé compterait Total trois fois ; construit sur
l'identifiant Wikidata, il compte juste.

Les quinze premières enseignes par libellé : Intermarché 1 679, TotalEnergies 1 209, Total 1 078,
Carrefour 1 024, Avia 726, E.Leclerc 651, Esso 494, Super U 409, Total Access 405, Système U 340,
Elan 285, Carrefour Market 270, Auchan 260, Esso Express 231, Vito 177.

### Accès réseau : trois constats

1. **`overpass-api.de` est injoignable depuis l'environnement de développement de la session.**
   L'hôte est pourtant autorisé par la politique réseau ; chaque tentative meurt sur
   `ws_closed_mid_exchange` — le tunnel vers le proxy sortant se ferme avant la fin de l'échange.
   Ce n'est ni un refus de politique (403/407) ni un problème de certificat.
2. **Depuis un runner GitHub, la première tentative a aussi échoué** (« Could not connect » en
   335 ms), puis la seconde, deux minutes plus tard, a réussi. L'instance est donc joignable mais
   capricieuse : le client doit réessayer et savoir basculer sur un miroir.
3. Licence **ODbL** : l'attribution d'OpenStreetMap est **obligatoire** partout où une enseigne
   est affichée. À prévoir dans le pied de page et dans `/v1/meta`.
