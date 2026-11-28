"""Les anecdotes calculées : quatre questions posées à la base.

`docs/specs/web.md` en fixe la liste et la règle qui compte vraiment : **chacune
repose sur une requête testée et un seuil minimal de données.** « Pas de
"historiquement" avec trois semaines d'historique. » Une anecdote qui n'atteint pas
son seuil n'est pas approximée : elle est absente, et la réponse dit pourquoi.

Rien n'est rédigé ici. L'API renvoie les chiffres et leur contexte ; le site les met
en français avec `Intl`, le serveur MCP avec ses propres formateurs testés. C'est la
convention du projet (`CLAUDE.md` § Conventions) et elle évite d'avoir deux
rédactions à garder d'accord.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from psycopg.rows import dict_row

from carburant_api.requetes.connexion import DELAI_CONNEXION, Pool

STATIONS_MIN_FRANCE: Final = 500
"""En dessous, « la station la moins chère de France » ne veut rien dire : on n'a pas
assez de stations pour que le mot « France » soit honnête."""

STATIONS_MIN_DEPARTEMENT: Final = 10
"""Un département à trois stations n'est pas comparable aux autres. Le classement
des départements les écarte plutôt que de les laisser gagner par accident."""

JOURS_MIN_SEMAINE: Final = 5
"""Sur les sept derniers jours, au moins cinq doivent avoir été calculés."""

STATIONS_MIN_AUTOROUTE: Final = 50
"""Le surcoût autoroutier se mesure sur un réseau, pas sur une poignée d'aires."""

SEMAINES_MIN_HISTORIQUE: Final = 52
"""Le seuil de la spec, chiffré : un an d'observations pour chaque jour de la
semaine. En dessous, on ne dit pas « historiquement »."""

LITRES_PLEIN_REFERENCE: Final = 50
"""Le plein de référence du surcoût autoroutier, fixé par la spec. C'est une unité
de comparaison affichée comme telle, pas une moyenne française mesurée."""


def _eur_l(valeur: Decimal | float) -> float:
    """Un prix ou un ecart de prix, au millieme d'euro.

    La base stocke des `numeric(5,3)` exacts ; les convertir en flottants pour les
    soustraire fait apparaitre du bruit (`2,399 - 1,833` donne
    `0,5660000000000001`). On arrondit a la precision de la source plutot que de
    publier ce bruit, qui n'a aucun sens pour un prix au litre.
    """
    return round(float(valeur), 3)


def _eur(valeur: Decimal | float) -> float:
    """Un montant en euros, au centime."""
    return round(float(valeur), 2)


def _centieme_de_centime(valeur: Decimal | float) -> float:
    """Un ecart hebdomadaire, au centieme de centime.

    Celui-la est petit par nature -- quelques millimes au litre -- et l'arrondir au
    millieme l'ecraserait a zero.
    """
    return round(float(valeur), 5)


@dataclass(frozen=True, slots=True)
class Indisponible:
    """Pourquoi une anecdote n'est pas calculable aujourd'hui.

    On la renvoie plutôt que de la taire : un recruteur qui lit l'API doit voir que
    le seuil existe et qu'il n'est pas atteint, pas croire que l'anecdote a été
    oubliée.
    """

    cle: str
    raison: str
    mesure: str


# ------------------------------------------------------------------ 1. ecart du jour
# L'écart entre la station la moins chère et la plus chère de France, aujourd'hui.
# Les deux stations sont nommées : c'est une donnée publique, et un écart sans ses
# deux bornes n'est pas vérifiable.
_ECART_DU_JOUR = """
WITH exploitables AS (
    SELECT q.station_id, q.prix, q.maj, s.ville, s.cp, s.code_departement, s.autoroute
      FROM marts.prix_courant_qualifie q
      JOIN marts.dim_station s ON s.id = q.station_id AND s.active
     WHERE q.carburant = %(carburant)s::text
       AND q.rupture_type IS NULL
       AND NOT q.suspect
       -- Un prix perime ou ancien ne temoigne plus du marche du jour. L'anecdote
       -- parle d'aujourd'hui : elle ne porte que sur les prix frais et recents.
       AND q.fraicheur IN ('frais', 'recent')
),
bornes AS (
    SELECT count(*)::integer AS stations, min(prix) AS prix_min, max(prix) AS prix_max
      FROM exploitables
)
SELECT b.stations,
       b.prix_min,
       b.prix_max,
       -- Egalite tranchee par l'identifiant : deux executions doivent nommer la meme
       -- station, sinon l'anecdote change sans que le marche ait bouge.
       (SELECT jsonb_build_object('station_id', station_id, 'ville', ville, 'cp', cp,
                                  'code_departement', code_departement,
                                  'autoroute', autoroute, 'prix_eur_l', prix, 'maj', maj)
          FROM exploitables ORDER BY prix, station_id LIMIT 1) AS moins_chere,
       (SELECT jsonb_build_object('station_id', station_id, 'ville', ville, 'cp', cp,
                                  'code_departement', code_departement,
                                  'autoroute', autoroute, 'prix_eur_l', prix, 'maj', maj)
          FROM exploitables ORDER BY prix DESC, station_id LIMIT 1) AS plus_chere
  FROM bornes b
"""

# ------------------------------------------------- 2. departement le moins cher
# Moyenne des medianes departementales sur les sept derniers jours calcules. On ne
# fixe pas la fenetre sur `current_date` : si la derniere collecte date d'hier, une
# fenetre calee sur aujourd'hui perdrait un jour pour rien.
_DEPARTEMENT_SEMAINE = """
WITH fin AS (
    SELECT max(jour) AS jour
      FROM marts.agregat_prix_jour
     WHERE carburant = %(carburant)s::text AND dimension = 'departement'
),
fenetre AS (
    SELECT a.valeur AS code_departement,
           avg(a.prix_median)      AS prix_median_moyen,
           min(a.stations)         AS stations_min,
           count(DISTINCT a.jour)::integer AS jours
      FROM marts.agregat_prix_jour a, fin
     WHERE a.carburant = %(carburant)s::text
       AND a.dimension = 'departement'
       AND a.jour > fin.jour - 7
       AND a.jour <= fin.jour
     GROUP BY a.valeur
    HAVING count(DISTINCT a.jour) >= %(jours_min)s
       AND min(a.stations) >= %(stations_min)s
),
national AS (
    SELECT avg(a.prix_median) AS prix_median_moyen
      FROM marts.agregat_prix_jour a, fin
     WHERE a.carburant = %(carburant)s::text
       AND a.dimension = 'france'
       AND a.valeur = ''
       AND a.jour > fin.jour - 7
       AND a.jour <= fin.jour
)
SELECT (SELECT jour FROM fin)                     AS jour_fin,
       (SELECT count(*)::integer FROM fenetre)    AS departements_retenus,
       (SELECT prix_median_moyen FROM national)   AS prix_national,
       f.code_departement,
       f.prix_median_moyen,
       f.stations_min,
       f.jours
  FROM fenetre f
 ORDER BY f.prix_median_moyen, f.code_departement
 LIMIT 1
"""

# ------------------------------------------------------- 3. surcout autoroutier
_SURCOUT_AUTOROUTE = """
WITH fin AS (
    SELECT max(jour) AS jour
      FROM marts.agregat_prix_jour
     WHERE carburant = %(carburant)s::text AND dimension = 'reseau'
)
SELECT fin.jour,
       max(a.prix_median) FILTER (WHERE a.valeur = 'autoroute') AS prix_autoroute,
       max(a.prix_median) FILTER (WHERE a.valeur = 'route')     AS prix_route,
       max(a.stations)    FILTER (WHERE a.valeur = 'autoroute') AS stations_autoroute,
       max(a.stations)    FILTER (WHERE a.valeur = 'route')     AS stations_route
  FROM marts.agregat_prix_jour a, fin
 WHERE a.carburant = %(carburant)s::text
   AND a.dimension = 'reseau'
   AND a.jour = fin.jour
 GROUP BY fin.jour
"""

# -------------------------------------------- 4. jour de la semaine le moins cher
# Le piege de cette anecdote : le prix du carburant a monte de 1,07 EUR a 1,86 EUR
# en seize ans. Moyenner les prix par jour de la semaine ne mesurerait donc pas
# l'effet du jour mais la tendance de fond -- et le gagnant serait le jour qui
# tombe le plus souvent au debut de la serie.
#
# On compare chaque jour a la moyenne des sept jours centres sur lui, puis on
# moyenne cet ecart par jour de la semaine. La tendance disparait, seul l'effet
# hebdomadaire reste.
#
# `RANGE` et non `ROWS` : la fenetre est de sept jours calendaires, et on exige
# `fenetre = 7` pour n'en garder que les completes. Avec `ROWS`, un trou dans la
# serie aurait fait porter la moyenne sur quatorze jours sans le dire.
_JOUR_SEMAINE = """
WITH serie AS (
    SELECT jour,
           prix_median,
           avg(prix_median) OVER glissante AS reference,
           count(*)         OVER glissante AS fenetre
      FROM marts.agregat_prix_jour
     WHERE carburant = %(carburant)s::text
       AND dimension = 'france'
       AND valeur = ''
     WINDOW glissante AS (
         ORDER BY jour
         RANGE BETWEEN '3 days' PRECEDING AND '3 days' FOLLOWING
     )
),
ecarts AS (
    SELECT extract(isodow FROM jour)::integer AS jour_semaine,
           prix_median - reference            AS ecart
      FROM serie
     WHERE fenetre = 7
)
SELECT jour_semaine,
       avg(ecart)     AS ecart_eur_l,
       count(*)::integer AS observations
  FROM ecarts
 GROUP BY jour_semaine
 ORDER BY avg(ecart), jour_semaine
"""


async def _une(pool: Pool, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(sql, params)
        return await curseur.fetchone()


async def _toutes(pool: Pool, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(sql, params)
        return await curseur.fetchall()


async def ecart_du_jour(pool: Pool, carburant: str) -> dict[str, Any] | Indisponible:
    """L'écart entre la station la moins chère et la plus chère de France."""
    ligne = await _une(pool, _ECART_DU_JOUR, {"carburant": carburant})
    stations = int(ligne["stations"]) if ligne else 0
    if ligne is None or stations < STATIONS_MIN_FRANCE:
        return Indisponible(
            cle="ecart_du_jour",
            raison=(
                f"Il faut au moins {STATIONS_MIN_FRANCE} stations avec un prix "
                "exploitable pour parler de la France entiere."
            ),
            mesure=f"{stations} stations exploitables",
        )
    return {
        "stations": stations,
        "prix_min_eur_l": _eur_l(ligne["prix_min"]),
        "prix_max_eur_l": _eur_l(ligne["prix_max"]),
        "ecart_eur_l": _eur_l(ligne["prix_max"] - ligne["prix_min"]),
        "moins_chere": ligne["moins_chere"],
        "plus_chere": ligne["plus_chere"],
    }


async def departement_moins_cher(pool: Pool, carburant: str) -> dict[str, Any] | Indisponible:
    """Le département le moins cher sur les sept derniers jours calculés."""
    ligne = await _une(
        pool,
        _DEPARTEMENT_SEMAINE,
        {
            "carburant": carburant,
            "jours_min": JOURS_MIN_SEMAINE,
            "stations_min": STATIONS_MIN_DEPARTEMENT,
        },
    )
    if ligne is None or ligne.get("code_departement") is None:
        return Indisponible(
            cle="departement_moins_cher",
            raison=(
                f"Il faut {JOURS_MIN_SEMAINE} jours d'agregats sur les sept derniers "
                f"et au moins {STATIONS_MIN_DEPARTEMENT} stations par departement."
            ),
            mesure="aucun departement ne remplit les deux conditions",
        )
    national = ligne["prix_national"]
    return {
        "code_departement": ligne["code_departement"],
        "prix_median_eur_l": _eur_l(ligne["prix_median_moyen"]),
        "prix_national_eur_l": _eur_l(national) if national is not None else None,
        "ecart_au_national_eur_l": (
            _eur_l(ligne["prix_median_moyen"] - national) if national is not None else None
        ),
        "stations": int(ligne["stations_min"]),
        "jours": int(ligne["jours"]),
        "jour_fin": ligne["jour_fin"],
        "departements_compares": int(ligne["departements_retenus"]),
    }


async def surcout_autoroute(pool: Pool, carburant: str) -> dict[str, Any] | Indisponible:
    """Ce que coûte en plus un plein de 50 L pris sur autoroute."""
    ligne = await _une(pool, _SURCOUT_AUTOROUTE, {"carburant": carburant})
    if ligne is None or ligne["prix_autoroute"] is None or ligne["prix_route"] is None:
        return Indisponible(
            cle="surcout_autoroute",
            raison="Il faut un agregat du jour pour l'autoroute et pour la route.",
            mesure="une des deux moities du reseau manque",
        )
    stations_autoroute = int(ligne["stations_autoroute"])
    if stations_autoroute < STATIONS_MIN_AUTOROUTE:
        return Indisponible(
            cle="surcout_autoroute",
            raison=f"Il faut au moins {STATIONS_MIN_AUTOROUTE} stations d'autoroute.",
            mesure=f"{stations_autoroute} stations d'autoroute",
        )
    ecart = ligne["prix_autoroute"] - ligne["prix_route"]
    return {
        "prix_autoroute_eur_l": _eur_l(ligne["prix_autoroute"]),
        "prix_route_eur_l": _eur_l(ligne["prix_route"]),
        "ecart_eur_l": _eur_l(ecart),
        "litres": LITRES_PLEIN_REFERENCE,
        "surcout_eur": _eur(ecart * LITRES_PLEIN_REFERENCE),
        "stations_autoroute": stations_autoroute,
        "stations_route": int(ligne["stations_route"]),
        "jour": ligne["jour"],
    }


async def jour_semaine_moins_cher(pool: Pool, carburant: str) -> dict[str, Any] | Indisponible:
    """Le jour de la semaine historiquement le moins cher, tendance de fond retirée."""
    lignes = await _toutes(pool, _JOUR_SEMAINE, {"carburant": carburant})
    observations = min((int(ligne["observations"]) for ligne in lignes), default=0)
    if len(lignes) < 7 or observations < SEMAINES_MIN_HISTORIQUE:
        return Indisponible(
            cle="jour_semaine_moins_cher",
            raison=(
                f"Il faut {SEMAINES_MIN_HISTORIQUE} semaines d'historique pour chacun "
                "des sept jours. On ne dit pas « historiquement » avant."
            ),
            mesure=(
                f"{len(lignes)} jours de la semaine couverts, "
                f"{observations} semaines pour le moins bien pourvu"
            ),
        )
    return {
        "jour_semaine": int(lignes[0]["jour_semaine"]),
        "ecart_eur_l": _centieme_de_centime(lignes[0]["ecart_eur_l"]),
        "semaines": observations,
        "classement": [
            {
                "jour_semaine": int(ligne["jour_semaine"]),
                "ecart_eur_l": _centieme_de_centime(ligne["ecart_eur_l"]),
            }
            for ligne in lignes
        ],
        "methode": (
            "Ecart a la moyenne des sept jours centres sur chaque date, moyenne par "
            "jour de la semaine. Sans ce retrait de tendance, le resultat mesurerait "
            "la hausse des prix sur seize ans, pas l'effet du jour."
        ),
    }
