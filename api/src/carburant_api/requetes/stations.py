"""Requetes SQL sur les stations.

SQL brut, pas d'ORM : les requetes geographiques et les agregats s'ecrivent mieux
ainsi, et on voit exactement ce qui part a la base. C'est aussi ce qui permet de
coller un `EXPLAIN ANALYZE` dans la documentation sans traduction.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Final, Literal

from psycopg.rows import dict_row

from carburant_api.requetes.connexion import DELAI_CONNEXION, Pool

RAYON_MAX_KM: Final = 50.0
"""Au-dela, la recherche n'a plus de sens : on ne fait pas 50 km pour economiser
quelques centimes, et la requete deviendrait couteuse."""

LIMITE_MAX: Final = 100
"""Plafond de pagination. Une liste plus longue ne se lit pas sur un telephone."""

type Tri = Literal["prix", "distance"]


@dataclass(frozen=True, slots=True)
class Recherche:
    """Les parametres d'une recherche de stations proches."""

    latitude: float
    longitude: float
    rayon_km: float
    carburant: str | None
    tri: Tri
    limite: int
    decalage: int
    # Les prix perimes (> 30 jours) sont exclus des recherches mais restent visibles
    # sur la fiche de la station. Les prix anciens, eux, sont gardes : les ecarter
    # priverait l'utilisateur de stations qui existent et vendent au prix affiche.
    inclure_perimes: bool = False


# Borne basse sur `maj`, seule chose qui empeche une recherche de traverser vingt ans
# d'historique. Sans elle, le plan reel fait un parcours d'index par station candidate
# **et par partition** -- 242 apres l'amorcage -- puis trie tout pour garder le dernier
# prix. Avec elle, PostgreSQL elague : trois partitions au lieu de 242 (verifie, douze
# sous-plans retires sur seize partitions locales).
#
# Elle ne change aucun resultat quand les prix perimes sont exclus, ce qui est le cas
# de toutes les recherches : l'horizon est place un jour **avant** le seuil de
# peremption, donc tout ce qu'il ecarte aurait de toute facon ete ecarte ensuite
# (`infra/migrations/011_horizon_recherche.sql`).
#
# Elle est donc **assemblee** plutot qu'ecrite en dur, parce qu'une recherche qui
# demande les prix perimes doit bien aller les chercher. Un `OR %(inclure_perimes)s`
# aurait suffi a la correction mais aurait tue l'elagage : PostgreSQL n'elague que sur
# une comparaison simple de la cle de partition. Rien d'exterieur n'entre dans cette
# interpolation.
_HORIZON_PROCHES = "AND f.maj >= marts.horizon_prix_exploitable()"

# Le `DISTINCT ON` prend le dernier changement de prix de chaque carburant. La vue
# `marts.prix_courant` fait la meme chose, mais on l'ecrit ici en toutes lettres pour
# pouvoir filtrer sur le carburant AVANT de chercher le dernier prix : sur une
# recherche mono-carburant, cela divise le travail par six.
# Les parametres portent un cast explicite : sans lui, PostgreSQL ne sait pas deduire
# le type de `%(carburant)s`, qui n'apparait que dans une comparaison a NULL et une
# egalite, et repond « could not determine data type of parameter ».
_SQL_PROCHES = """
WITH point AS (
    SELECT ST_SetSRID(
               ST_MakePoint(%(lon)s::double precision, %(lat)s::double precision),
               4326
           )::geography AS g
),
candidates AS (
    SELECT s.id, s.adresse, s.ville, s.cp, s.departement, s.code_departement,
           s.autoroute,
           -- L'enseigne vient d'OpenStreetMap et couvre plus de 99 stations sur
           -- 100. Pas de signe pour-cent dans ce commentaire : psycopg le lit comme
           -- un marqueur de parametre et refuse la requete. Trouve par les tests
           -- d'integration, en une seconde, apres l'avoir ecrit sans y penser. Elle
           -- manquait a cette requete alors que la fiche et la meilleure station la
           -- rendaient deja : le champ existait dans le schema, sous forme de
           -- propriete rendant toujours `None` depuis le Jalon 1.
           s.enseigne, s.enseigne_source, s.enseigne_score, s.enseigne_osm,
           ST_Y(s.geom::geometry) AS latitude,
           ST_X(s.geom::geometry) AS longitude,
           ST_Distance(s.geom, point.g) / 1000.0 AS distance_km
      FROM marts.dim_station s, point
     WHERE s.active
       AND ST_DWithin(s.geom, point.g, %(rayon_m)s::double precision)
),
prix AS (
    SELECT DISTINCT ON (f.station_id, f.carburant)
           f.station_id, f.carburant, f.prix, f.maj,
           marts.classe_fraicheur(f.maj) AS fraicheur
      FROM marts.fact_prix f
      JOIN candidates c ON c.id = f.station_id
     WHERE (%(carburant)s::text IS NULL OR f.carburant = %(carburant)s::text)
       {horizon}
     ORDER BY f.station_id, f.carburant, f.maj DESC
),
retenues AS (
    SELECT c.*, p.carburant, p.prix, p.maj, p.fraicheur,
           r.type AS rupture_type, r.debut AS rupture_debut
      FROM candidates c
      JOIN prix p ON p.station_id = c.id
      LEFT JOIN marts.rupture r
             ON r.station_id = c.id AND r.carburant = p.carburant
     WHERE (%(inclure_perimes)s::boolean OR p.fraicheur <> 'perime')
       -- Un carburant en rupture est exclu des recherches, et affiche comme tel
       -- sur la fiche de la station.
       AND r.type IS NULL
)
SELECT * FROM retenues
 ORDER BY {ordre}
"""

_ORDRES: Final[dict[str, str]] = {
    # Prix croissant, puis distance : a prix egal, la plus proche d'abord. Les prix
    # nuls (carburant sans prix) passent en dernier.
    "prix": "prix ASC NULLS LAST, distance_km ASC, id",
    "distance": "distance_km ASC, prix ASC NULLS LAST, id",
}


async def stations_proches(pool: Pool, recherche: Recherche) -> tuple[list[dict[str, Any]], int]:
    """Les stations autour d'un point. Renvoie (lignes, nombre total de stations).

    Les lignes sont au grain station x carburant : l'appelant les regroupe par
    station. Le total compte les stations distinctes avant pagination.
    """
    ordre = _ORDRES[recherche.tri]
    requete = _SQL_PROCHES.format(
        ordre=ordre,
        horizon="" if recherche.inclure_perimes else _HORIZON_PROCHES,
    )

    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(
            requete,
            {
                "lat": recherche.latitude,
                "lon": recherche.longitude,
                "rayon_m": recherche.rayon_km * 1000.0,
                "carburant": recherche.carburant,
                "inclure_perimes": recherche.inclure_perimes,
            },
        )
        lignes = await curseur.fetchall()

    # `count(DISTINCT id) OVER ()` n'existe pas dans PostgreSQL. Comme on regroupe
    # de toute facon par station cote applicatif, on compte les identifiants
    # distincts ici plutot que d'ajouter une seconde requete.
    total = len({ligne["id"] for ligne in lignes})
    return lignes, total


# `/v1/meta` sert aussi de sonde de vivacite au conteneur (voir
# `infra/docker/api.Dockerfile`), avec quatre secondes de budget. Il ne peut donc
# contenir aucune requete lourde.
#
# **Le nombre de changements de prix est une estimation, et c'est delibere.**
# `count(*) FROM marts.fact_prix` parcourt 64 millions de lignes reparties sur
# 242 partitions, soit 8 Go : trente a quarante secondes sur le VPS. Cette requete
# etait inoffensive au Jalon 1, quand la table contenait 33 000 lignes ; l'amorcage
# de l'historique l'a rendue mortelle, et c'est le healthcheck qui l'a signale en
# faisant echouer un deploiement. On lit donc l'estimation que PostgreSQL tient a
# jour dans son catalogue, somme sur les partitions.
#
# `greatest(reltuples, 0)` : depuis PostgreSQL 14, `reltuples` vaut **-1** pour une
# table jamais analysee -- une partition creee a l'instant, par exemple. Sans ce
# garde-fou, une partition neuve retrancherait une unite au total.
#
# Le champ s'appelle `prix_connus_environ` pour que personne, front ou serveur MCP,
# ne presente ce chiffre comme exact.
_SQL_META = """
SELECT (SELECT max(fin) FROM meta.execution_etl WHERE statut = 'succes')
           AS derniere_collecte,
       (SELECT count(*) FROM marts.dim_station WHERE active)
           AS stations_actives,
       (SELECT coalesce(sum(greatest(c.reltuples, 0)), 0)::bigint
          FROM pg_class c
          JOIN pg_inherits i ON i.inhrelid = c.oid
         WHERE i.inhparent = 'marts.fact_prix'::regclass)
           AS prix_connus_environ,
       (SELECT array_agg(code ORDER BY ordre) FROM marts.dim_carburant)
           AS carburants
"""


@dataclass(frozen=True, slots=True)
class Meta:
    """Ce que `/v1/meta` expose sur l'etat des donnees."""

    derniere_collecte: dt.datetime | None
    stations_actives: int
    prix_connus_environ: int
    """Estimation, pas un comptage. Voir `_SQL_META`."""
    carburants: list[str]


async def lire_meta(pool: Pool) -> Meta:
    """Etat des donnees servies : derniere collecte, volumes, carburants."""
    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(_SQL_META)
        ligne = await curseur.fetchone()

    if ligne is None:  # pragma: no cover - la requete rend toujours une ligne
        return Meta(None, 0, 0, [])
    return Meta(
        derniere_collecte=ligne["derniere_collecte"],
        stations_actives=int(ligne["stations_actives"] or 0),
        prix_connus_environ=int(ligne["prix_connus_environ"] or 0),
        carburants=list(ligne["carburants"] or []),
    )


_SQL_FICHE = """
SELECT s.id, s.adresse, s.ville, s.cp, s.departement, s.code_departement,
       s.region, s.autoroute, s.horaires, s.services,
       s.enseigne, s.enseigne_source, s.enseigne_score, s.enseigne_osm,
       s.premiere_vue, s.derniere_vue, s.active,
       ST_Y(s.geom::geometry) AS latitude,
       ST_X(s.geom::geometry) AS longitude
  FROM marts.dim_station s
 WHERE s.id = %(id)s::bigint
"""

# Tous les carburants de la station, y compris ceux dont le prix est perime ou qui
# sont en rupture : contrairement a une recherche, une fiche ne cache rien. Elle
# affiche la date et l'etat, et laisse le lecteur juger.
_SQL_FICHE_PRIX = """
SELECT DISTINCT ON (f.carburant)
       f.carburant, f.prix, f.maj,
       marts.classe_fraicheur(f.maj) AS fraicheur,
       r.type AS rupture_type, r.debut AS rupture_debut
  FROM marts.fact_prix f
  LEFT JOIN marts.rupture r ON r.station_id = f.station_id AND r.carburant = f.carburant
 WHERE f.station_id = %(id)s::bigint
 ORDER BY f.carburant, f.maj DESC
"""

_SQL_HISTORIQUE = """
SELECT carburant, prix, maj
  FROM marts.fact_prix
 WHERE station_id = %(id)s::bigint
   AND (%(carburant)s::text IS NULL OR carburant = %(carburant)s::text)
   AND maj >= %(depuis)s::timestamptz
 ORDER BY maj DESC, carburant
 LIMIT %(limite)s::integer
"""


async def fiche(pool: Pool, station_id: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Une station et tous ses prix courants, perimes et ruptures compris."""
    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(_SQL_FICHE, {"id": station_id})
        station = await curseur.fetchone()
        if station is None:
            return None, []
        await curseur.execute(_SQL_FICHE_PRIX, {"id": station_id})
        prix = await curseur.fetchall()
    return station, prix


async def historique(
    pool: Pool,
    station_id: int,
    *,
    carburant: str | None,
    depuis: dt.datetime,
    limite: int,
) -> list[dict[str, Any]]:
    """Les changements de prix d'une station depuis une date.

    Le grain de `fact_prix` etant « un changement de prix », cet historique est
    exactement ce que la source a publie : aucun echantillonnage, aucun lissage.
    """
    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(
            _SQL_HISTORIQUE,
            {"id": station_id, "carburant": carburant, "depuis": depuis, "limite": limite},
        )
        return await curseur.fetchall()
