"""Amorcage de l'historique depuis une archive annuelle.

Une archive annuelle, c'est jusqu'a 5,3 millions de changements de prix pour une
seule annee. Trois contraintes en decoulent, et expliquent tout ce fichier :

1. **Rien ne tient en memoire.** La lecture est en streaming (voir
   `carburant_etl.sources.archives`) et le chargement se fait par lots.
2. **`COPY`, pas des `INSERT`.** Cinq millions d'`INSERT` prendraient des heures ;
   un `COPY` de 5,3 M de lignes prend 14 secondes (mesure de la reconnaissance). On
   copie dans une table temporaire, puis on insere de la vers `fact_prix` avec
   `ON CONFLICT DO NOTHING`.
3. **Relancer doit etre sans effet.** Une archive a moitie chargee, une coupure
   reseau, un essai : rejouer la meme annee ne doit creer aucun doublon.

## Ce que l'amorcage ne fait pas

Il **ne touche pas aux stations que le flux connait deja**. Une station vivante a une
adresse, un departement et des horaires a jour, venus du flux instantane ; l'archive
2007 en a une version de dix-neuf ans d'age. L'amorcage se contente d'avancer leur
`premiere_vue` vers le passe.

Les stations que l'archive est seule a connaitre -- fermees depuis -- sont creees
**inactives** : elles n'apparaissent dans aucune recherche, mais leur historique de
prix existe et reste consultable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import psycopg

from carburant_etl.chargement.marts import assurer_partitions
from carburant_etl.chargement.verrou import exclusif
from carburant_etl.sources.archives import PrixArchive, StationArchive, lire, telecharger

journal = logging.getLogger("carburant.backfill")

TAILLE_LOT: Final = 250_000
"""Nombre de prix par lot. 250 000 lignes tiennent largement en memoire et donnent
des `COPY` assez gros pour que le cout fixe par lot devienne negligeable."""


@dataclass(frozen=True, slots=True)
class ResultatBackfill:
    """Ce qu'une annee d'archive a apporte."""

    annee: int
    collecte_id: int
    stations_lues: int
    stations_creees: int
    prix_lus: int
    prix_inseres: int
    prix_deja_connus: int
    partitions_creees: list[str]
    rejets: dict[str, object]
    duree_secondes: float


_TABLE_TEMPORAIRE = """
CREATE TEMPORARY TABLE lot_prix (
    station_id bigint       NOT NULL,
    carburant  text         NOT NULL,
    prix       numeric(5,3) NOT NULL,
    maj        timestamptz  NOT NULL
) ON COMMIT DROP
"""

# `ON CONFLICT DO NOTHING` et non `DO UPDATE` : contrairement a une collecte, une
# archive ne reobserve rien. Si le prix est deja la, c'est qu'une autre source l'a
# vu, et sa `derniere_observation` est plus juste que la notre.
_INSERER_PRIX = """
INSERT INTO marts.fact_prix
    (station_id, carburant, prix, maj, premiere_collecte, derniere_observation)
SELECT l.station_id, l.carburant, l.prix, l.maj, %(collecte_id)s, l.maj
  FROM lot_prix l
  -- Une station rejetee par le filtre d'emprise n'existe pas dans dim_station :
  -- sans cette jointure, la cle etrangere ferait echouer tout le lot.
  JOIN marts.dim_station s ON s.id = l.station_id
ON CONFLICT (station_id, carburant, maj) DO NOTHING
"""

# Les stations deja connues ne sont pas ecrasees : on ne fait qu'avancer leur
# premiere_vue vers le passe. `active` n'est jamais touche.
_INSERER_STATIONS = """
INSERT INTO marts.dim_station
    (id, geom, cp, adresse, ville, code_departement, autoroute,
     premiere_vue, derniere_vue, active)
VALUES (%(id)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography,
        %(cp)s, %(adresse)s, %(ville)s, %(dep)s, %(autoroute)s,
        %(vue)s, %(vue)s, false)
ON CONFLICT (id) DO UPDATE SET
    premiere_vue = least(marts.dim_station.premiere_vue, EXCLUDED.premiere_vue)
"""


def departement_depuis_cp(cp: str | None) -> str | None:
    """Le code departement deduit du code postal.

    Les archives ne donnent ni departement ni region, contrairement au flux : il faut
    le deduire. Deux cas particuliers :

    - **la Corse** : les codes postaux en `20xxx` ne disent pas s'il s'agit de la
      Corse-du-Sud (2A) ou de la Haute-Corse (2B). On ne devine pas : `None`. Les
      stations corses encore vivantes ont de toute facon leur departement du flux.
    - **les DROM** (`97x`, `98x`) : hors emprise, donc deja ecartes en amont.
    """
    if not cp or len(cp) < 2 or not cp[:2].isdigit():
        return None
    prefixe = cp[:2]
    if prefixe == "20":
        return None
    if prefixe == "97" or prefixe == "98":
        return None
    return prefixe


def enregistrer_collecte_archive(
    connexion: psycopg.Connection[tuple[object, ...]], annee: int, chemin: Path
) -> int:
    """Une ligne dans `raw.collecte` pour cette archive, comme pour une collecte."""
    empreinte = hashlib.sha256(chemin.read_bytes()).hexdigest()
    maintenant = dt.datetime.now(tz=dt.UTC)
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO raw.collecte (source, url, debut, fin, octets, sha256, chemin, statut)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'en_cours')
            RETURNING id
            """,
            (
                f"archive-{annee}",
                f"https://donnees.roulez-eco.fr/opendata/annee/{annee}",
                maintenant,
                maintenant,
                chemin.stat().st_size,
                empreinte,
                str(chemin),
            ),
        )
        ligne = curseur.fetchone()
    if ligne is None or not isinstance(ligne[0], int):
        raise RuntimeError(f"collecte d archive : identifiant inattendu {ligne!r}")
    return ligne[0]


def mois_de_l_annee(annee: int) -> set[tuple[int, int]]:
    """Les douze mois de l'annee, plus decembre de l'annee precedente.

    Decembre precedent parce que les bornes de partition sont en UTC : un prix du
    1er janvier a 00 h 30 heure de Paris est un 31 decembre en UTC, et tomberait
    sinon dans la partition DEFAULT. Mesure : 3 612 lignes pour l'archive 2025.
    """
    mois = {(annee, m) for m in range(1, 13)}
    mois.add((annee - 1, 12))
    return mois


def _par_lots(
    source: Iterator[tuple[StationArchive, list[PrixArchive]]], taille: int
) -> Iterator[tuple[list[StationArchive], list[PrixArchive]]]:
    """Regroupe le flux station par station en lots d'au plus `taille` prix."""
    stations: list[StationArchive] = []
    prix: list[PrixArchive] = []
    for station, lignes in source:
        stations.append(station)
        prix.extend(lignes)
        if len(prix) >= taille:
            yield stations, prix
            stations, prix = [], []
    if stations or prix:
        yield stations, prix


def _charger_stations(
    connexion: psycopg.Connection[tuple[object, ...]],
    stations: Sequence[StationArchive],
    vue: dt.datetime,
) -> int:
    """Insere les stations inconnues, avance la premiere vue des autres."""
    if not stations:
        return 0
    with connexion.cursor() as curseur:
        avant = _compter_stations(curseur)
        curseur.executemany(
            _INSERER_STATIONS,
            [
                {
                    "id": s.station_id,
                    "lon": s.longitude,
                    "lat": s.latitude,
                    "cp": s.cp,
                    "adresse": s.adresse,
                    "ville": s.ville,
                    "dep": departement_depuis_cp(s.cp),
                    "autoroute": s.pop == "A",
                    "vue": vue,
                }
                for s in stations
            ],
        )
        apres = _compter_stations(curseur)
    return apres - avant


def _compter_stations(curseur: psycopg.Cursor[tuple[object, ...]]) -> int:
    curseur.execute("SELECT count(*) FROM marts.dim_station")
    ligne = curseur.fetchone()
    return int(ligne[0]) if ligne and isinstance(ligne[0], int) else 0


def _charger_prix(
    connexion: psycopg.Connection[tuple[object, ...]],
    prix: Sequence[PrixArchive],
    collecte_id: int,
) -> int:
    """Copie un lot puis l'insere. Renvoie le nombre de lignes reellement ajoutees."""
    if not prix:
        return 0
    with connexion.cursor() as curseur:
        curseur.execute(_TABLE_TEMPORAIRE)
        with curseur.copy("COPY lot_prix (station_id, carburant, prix, maj) FROM STDIN") as copie:
            for ligne in prix:
                copie.write_row((ligne.station_id, ligne.carburant, ligne.prix, ligne.maj))
        curseur.execute(_INSERER_PRIX, {"collecte_id": collecte_id})
        return curseur.rowcount


def amorcer(
    connexion: psycopg.Connection[tuple[object, ...]],
    annee: int,
    *,
    repertoire: Path,
    user_agent: str,
    taille_lot: int = TAILLE_LOT,
) -> ResultatBackfill:
    """Charge une annee d'archive. Idempotent : la rejouer n'ajoute rien.

    Prend le verrou d'exclusion : un amorcage dure une heure, et la collecte se
    declenche toutes les quinze minutes.
    """
    with exclusif(connexion, operation=f"amorcage {annee}"):
        return _amorcer(
            connexion,
            annee,
            repertoire=repertoire,
            user_agent=user_agent,
            taille_lot=taille_lot,
        )


def _amorcer(
    connexion: psycopg.Connection[tuple[object, ...]],
    annee: int,
    *,
    repertoire: Path,
    user_agent: str,
    taille_lot: int,
) -> ResultatBackfill:
    """Le corps de `amorcer`, une fois le verrou obtenu."""
    debut = dt.datetime.now(tz=dt.UTC)
    chemin = telecharger(annee, repertoire, user_agent=user_agent)
    collecte_id = enregistrer_collecte_archive(connexion, annee, chemin)

    partitions = assurer_partitions(connexion, mois_de_l_annee(annee))

    # Les stations de l'archive sont vues comme presentes au 1er janvier de l'annee :
    # c'est la seule date dont on dispose a coup sur pour elles.
    vue = dt.datetime(annee, 1, 1, tzinfo=dt.UTC)

    iterateur, rejets = lire(chemin)
    stations_lues = stations_creees = prix_lus = prix_inseres = 0

    for lot_stations, lot_prix in _par_lots(iterateur, taille_lot):
        with connexion.transaction():
            stations_creees += _charger_stations(connexion, lot_stations, vue)
            prix_inseres += _charger_prix(connexion, lot_prix, collecte_id)
        stations_lues += len(lot_stations)
        prix_lus += len(lot_prix)
        journal.info(
            "annee %d : %d stations, %d prix lus, %d inseres",
            annee,
            stations_lues,
            prix_lus,
            prix_inseres,
        )

    duree = (dt.datetime.now(tz=dt.UTC) - debut).total_seconds()
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(
            "UPDATE raw.collecte SET statut = 'succes', fin = now(), lignes = %s WHERE id = %s",
            (prix_lus, collecte_id),
        )

    return ResultatBackfill(
        annee=annee,
        collecte_id=collecte_id,
        stations_lues=stations_lues,
        stations_creees=stations_creees,
        prix_lus=prix_lus,
        prix_inseres=prix_inseres,
        prix_deja_connus=prix_lus - prix_inseres,
        partitions_creees=partitions,
        rejets=rejets.en_dictionnaire(),
        duree_secondes=duree,
    )
