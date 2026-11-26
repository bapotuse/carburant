# Faut-il passer la couche de transformation à dbt ?

Demandé par `docs/specs/donnees.md` en fin de Jalon 2 : apports, coût, recommandation.
Rien n'est migré sans accord.

**Recommandation en une phrase : non pour l'ingestion, oui à évaluer pour la couche
d'agrégats après le Jalon 3.** Le détail suit.

## Ce qu'est dbt, en trois phrases

dbt est un outil qui transforme des données **déjà dans la base**. On écrit des
`SELECT` dans des fichiers `.sql`, dbt se charge de les matérialiser en tables ou en
vues, dans le bon ordre, en déduisant les dépendances des références entre modèles.
Il apporte avec cela des tests déclaratifs, une documentation générée et un graphe de
lignage navigable.

Ce qu'il ne fait pas : extraire, charger, appeler une API, lire un XML de 386 Mo en
streaming. Le `E` et le `L` d'ETL restent du Python.

## Ce que le projet a déjà, et qui recouvre une partie des apports

| Apport de dbt | Ce qu'on a aujourd'hui |
|---|---|
| Tests déclaratifs (`unique`, `not_null`, `accepted_values`) | Huit contrôles qualité en SQL, exécutés à chaque run, avec verdict et mesure lisible. Plus 60 tests d'intégration contre une vraie base PostGIS. |
| Documentation générée | Chaque table et chaque colonne porte un `COMMENT ON` qui dit **pourquoi**, pas seulement quoi. `docs/comprendre-le-projet.md` pour l'ensemble. |
| Lignage | Quatre migrations et trois modules de chargement : le graphe tient dans une tête. Il ne tiendra plus à trente modèles. |
| Matérialisations incrémentales | `INSERT … ON CONFLICT` sur un grain « un changement de prix », avec partitions mensuelles créées à la volée. |

Autrement dit, dbt apporterait surtout du **lignage** et une **façon standard** de
dire ce qu'on dit déjà à la main.

## Ce qui résiste franchement à dbt

**`fact_prix` n'est pas un modèle dbt naturel.** Son grain est « un changement de
prix », son chargement est un `ON CONFLICT DO UPDATE` qui ne touche qu'une colonne, et
sa table est partitionnée par mois avec création des partitions à l'exécution. Les
matérialisations incrémentales de `dbt-postgres` font un `delete+insert` ou un `merge`
sur une table unique : reproduire la logique actuelle demanderait des macros et du
SQL pré-hook, c'est-à-dire réécrire en dbt ce qui tient aujourd'hui en 80 lignes de
Python lisibles.

**L'amorçage est intrinsèquement du Python.** Lire en streaming un zip XML de 386 Mo,
basculer entre millièmes et euros selon la valeur, filtrer une emprise géographique,
compter six catégories de rejets : dbt n'a rien à dire là-dessus.

**Deux outils de migration cohabiteraient.** Le schéma est versionné par dix fichiers
SQL numérotés, avec un lanceur qui refuse de continuer si un fichier déjà appliqué a
changé. dbt a sa propre idée de la gestion du schéma. Faire vivre les deux, c'est deux
sources de vérité sur la forme de la base.

## Ce qui, au contraire, lui irait bien

La **couche d'agrégats** est du SQL sur du SQL, sans effet de bord :

- `marts.reference_departementale` (vue matérialisée)
- `marts.agregat_prix_jour`
- `marts.prix_courant` et `marts.prix_courant_qualifie`
- `marts.classement_enseigne`, `marts.couverture_enseigne`, `marts.rupture_courante`

C'est exactement le terrain de dbt : des modèles qui dépendent les uns des autres, un
ordre de rafraîchissement à tenir, des tests de cohérence à déclarer. Aujourd'hui cet
ordre est tenu par une fonction Python de quinze lignes, et c'est suffisant **tant
qu'il y a sept objets**. À vingt, le lignage cesserait d'être un luxe.

## Le coût, chiffré

| Poste | Estimation |
|---|---|
| Dépendance | `dbt-core` + `dbt-postgres`, et leurs transitives — une trentaine de paquets, dont une partie du monde Jinja |
| Image ETL | +80 à 120 Mo, à construire pour deux architectures |
| Réécriture | les sept objets ci-dessus, soit ~400 lignes de SQL à redécouper en modèles, plus `profiles.yml`, `dbt_project.yml`, et les tests déclaratifs |
| Temps | une journée de travail, et une demi-journée pour que la CI le fasse tourner contre un vrai PostGIS |
| Risque | deux systèmes de migration à faire cohabiter ; un `dbt run` dans la boucle de quinze minutes ajoute son temps de démarrage à chaque collecte |

## L'argument qu'on n'invoquera pas

dbt est recherché dans les offres de data engineering, et il serait tentant de
l'ajouter pour cela. Ce serait un mauvais service : un recruteur qui ouvre le dépôt
verra tout de suite si l'outil sert ou s'il décore. « Je n'ai pas pris dbt, et voici
pourquoi » se défend très bien en entretien — mieux, souvent, qu'un `dbt_project.yml`
qu'on ne saurait pas justifier. Le projet a une règle là-dessus : toute dépendance
doit se justifier.

## Recommandation

1. **Ne pas migrer l'ingestion.** Le rapport coût/apport est mauvais, et la partie
   spécifique du projet — grain, partitions, streaming — est précisément celle que
   dbt ne simplifie pas.
2. **Réévaluer pour la couche d'agrégats après le Jalon 3**, quand l'API aura montré
   quels agrégats servent vraiment et lesquels sont morts-nés. Migrer une couche
   stabilisée coûte une journée ; migrer une couche encore mouvante coûte deux fois.
3. **Trois critères de déclenchement**, écrits d'avance pour que la décision ne soit
   pas une humeur :
   - plus de quinze objets dans `marts` ;
   - une dépendance entre agrégats qu'il faut documenter ailleurs que dans le code ;
   - un second développeur sur le projet.
4. **En attendant, emprunter ses bonnes idées sans l'outil** : c'est déjà le cas pour
   les tests exécutés à chaque run et les commentaires sur chaque colonne.

Décision à prendre par Baptiste. Par défaut, sans réponse de sa part : on ne migre
pas, et le point est reposé à la fin du Jalon 3.
