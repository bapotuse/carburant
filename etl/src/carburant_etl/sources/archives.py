"""Archives annuelles de roulez-eco : lecture en streaming d'un zip XML.

Une archive annuelle contient un `<pdv>` par station, et **sous chaque station tous
ses changements de prix de l'annee**. L'annee 2025 pese 386 Mo de XML decompresse
pour 5,3 millions de `<prix>` : on ne charge jamais le document en memoire, on le lit
avec `iterparse` en vidant chaque station apres l'avoir traitee, directement depuis
le zip sans decompresser sur disque.

**Le schema change selon l'annee.** Mesures de la reconnaissance
(`docs/reconnaissance.md` section 2) :

| Aspect           | 2007 - 2021            | 2022 - 2026 |
|------------------|------------------------|-------------|
| Unite des prix   | millemes (`999`)       | euros (`1.809`) |
| Horaires         | `<ouverture>`          | `<horaires>` (depuis 2018) |
| Format de `maj`  | espace + microsecondes | `T`, et quelques espaces |

Les deux formats de `maj` **coexistent dans un meme fichier** : 2025 contient
5 297 800 dates au format `T` et 96 au format espace. Le parseur accepte les deux,
avec ou sans microsecondes -- c'est deja ce que fait `carburant_etl.fuseau.lire_maj`.

La conversion des prix ne depend pas de l'annee mais de la valeur :
**`si valeur > 20 alors valeur / 1000`**. Aucun carburant ne vaut 20 EUR le litre, et
aucun ne vaut 20 millemes : la regle est sans ambiguite, et elle survivra a une
bascule d'unite qu'on n'aurait pas vue venir.

**Les coordonnees des archives sont sales** : latitude brute de -2 094 971 (La
Reunion) a 6 260 656 (au nord de la Norvege, aberration pure), 3 539 valeurs non
entieres, 70 stations hors emprise en 2025. On filtre sur la France metropolitaine et
la Corse, et **on compte les rejets**.
"""

from __future__ import annotations

import datetime as dt
import logging
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from xml.etree.ElementTree import Element, iterparse

import httpx

from carburant_etl.carburants import (
    CarburantInconnu,
    CodeCarburant,
    depuis_nom_flux,
    est_dans_les_bornes,
)
from carburant_etl.fuseau import HorodatageIllisible, lire_maj

journal = logging.getLogger("carburant.archives")

RACINE: Final = "https://donnees.roulez-eco.fr/opendata/annee"
PREMIERE_ANNEE: Final = 2007

# Emprise France metropolitaine + Corse, en degres. Les DROM des archives et les
# aberrations tombent dehors. Memes bornes que le controle qualite.
LONGITUDE_MIN: Final = -5.3
LONGITUDE_MAX: Final = 9.7
LATITUDE_MIN: Final = 41.2
LATITUDE_MAX: Final = 51.2

# Au-dela, la valeur est en millemes. En deca, elle est en euros. Aucun carburant
# n'a jamais valu 20 EUR le litre ni 20 millemes.
SEUIL_MILLIEMES: Final = 20.0

TIMEOUT: Final = httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0)


@dataclass(frozen=True, slots=True)
class PrixArchive:
    """Un changement de prix lu dans une archive."""

    station_id: int
    carburant: CodeCarburant
    prix: float
    maj: dt.datetime


@dataclass(frozen=True, slots=True)
class StationArchive:
    """Une station telle que l'archive la decrit, coordonnees deja converties."""

    station_id: int
    longitude: float
    latitude: float
    cp: str | None
    adresse: str | None
    ville: str | None
    pop: str | None


@dataclass
class RejetsArchive:
    """Ce que l'archive contenait d'inexploitable, par motif."""

    stations_hors_emprise: int = 0
    stations_sans_coordonnees: int = 0
    prix_malformes: int = 0
    prix_hors_bornes: int = 0
    maj_illisibles: int = 0
    carburants_inconnus: int = 0
    exemples: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return (
            self.stations_hors_emprise
            + self.stations_sans_coordonnees
            + self.prix_malformes
            + self.prix_hors_bornes
            + self.maj_illisibles
            + self.carburants_inconnus
        )

    def noter(self, motif: str, exemple: str) -> None:
        """Garde un exemple par motif : un compteur sans exemple n'aide personne."""
        self.exemples.setdefault(motif, exemple)

    def en_dictionnaire(self) -> dict[str, object]:
        return {
            "stations_hors_emprise": self.stations_hors_emprise,
            "stations_sans_coordonnees": self.stations_sans_coordonnees,
            "prix_malformes": self.prix_malformes,
            "prix_hors_bornes": self.prix_hors_bornes,
            "maj_illisibles": self.maj_illisibles,
            "carburants_inconnus": self.carburants_inconnus,
            "exemples": self.exemples,
        }


def url_archive(annee: int) -> str:
    return f"{RACINE}/{annee}"


def convertir_prix(valeur: float) -> float:
    """Millemes ou euros, selon la valeur et non selon l'annee.

    >>> convertir_prix(999)
    0.999
    >>> convertir_prix(1.809)
    1.809
    """
    return valeur / 1000 if valeur > SEUIL_MILLIEMES else valeur


def convertir_coordonnee(brute: str) -> float:
    """Degres x 100 000, et pas forcement entiers : 3 539 valeurs decimales en 2025."""
    return float(brute) / 100_000


def dans_l_emprise(longitude: float, latitude: float) -> bool:
    return LONGITUDE_MIN <= longitude <= LONGITUDE_MAX and LATITUDE_MIN <= latitude <= LATITUDE_MAX


def telecharger(annee: int, repertoire: Path, *, user_agent: str) -> Path:
    """Telecharge l'archive d'une annee, ou reutilise celle deja sur disque.

    Les archives des annees passees ne changent plus : la retelecharger a chaque essai
    serait une impolitesse envers un service public, et une perte de temps.
    """
    repertoire.mkdir(parents=True, exist_ok=True)
    chemin = repertoire / f"archive-{annee}.zip"
    if chemin.exists() and chemin.stat().st_size > 0:
        journal.info("archive %d deja sur disque (%.1f Mo)", annee, chemin.stat().st_size / 1e6)
        return chemin

    url = url_archive(annee)
    journal.info("telechargement de %s", url)
    partiel = chemin.with_suffix(".zip.partiel")
    with (
        httpx.Client(
            timeout=TIMEOUT, headers={"User-Agent": user_agent}, follow_redirects=True
        ) as client,
        client.stream("GET", url) as reponse,
    ):
        reponse.raise_for_status()
        with partiel.open("wb") as fichier:
            for morceau in reponse.iter_bytes(chunk_size=1 << 20):
                fichier.write(morceau)
    # Renommage final : un fichier tronque par une coupure ne doit pas passer pour
    # une archive complete au prochain essai.
    partiel.rename(chemin)
    journal.info("archive %d : %.1f Mo", annee, chemin.stat().st_size / 1e6)
    return chemin


def _station_depuis(element: Element, rejets: RejetsArchive) -> StationArchive | None:
    brut_id = element.get("id")
    if not brut_id or not brut_id.isdigit():
        rejets.stations_sans_coordonnees += 1
        rejets.noter("station sans identifiant", repr(brut_id))
        return None

    brut_lat, brut_lon = element.get("latitude"), element.get("longitude")
    if not brut_lat or not brut_lon:
        rejets.stations_sans_coordonnees += 1
        rejets.noter("station sans coordonnees", brut_id)
        return None
    try:
        latitude = convertir_coordonnee(brut_lat)
        longitude = convertir_coordonnee(brut_lon)
    except ValueError:
        rejets.stations_sans_coordonnees += 1
        rejets.noter("coordonnees illisibles", f"{brut_id} {brut_lat},{brut_lon}")
        return None

    if not dans_l_emprise(longitude, latitude):
        rejets.stations_hors_emprise += 1
        rejets.noter(
            "hors France metropolitaine et Corse", f"{brut_id} {latitude:.3f},{longitude:.3f}"
        )
        return None

    adresse = (element.findtext("adresse") or "").strip() or None
    ville = (element.findtext("ville") or "").strip() or None
    pop = element.get("pop")
    return StationArchive(
        station_id=int(brut_id),
        longitude=longitude,
        latitude=latitude,
        cp=(element.get("cp") or "").strip() or None,
        adresse=adresse,
        ville=ville,
        pop=pop if pop in ("R", "A") else None,
    )


def _prix_depuis(element: Element, station_id: int, rejets: RejetsArchive) -> Iterator[PrixArchive]:
    for noeud in element.iterfind("prix"):
        nom, brut_maj, brut_valeur = noeud.get("nom"), noeud.get("maj"), noeud.get("valeur")
        if not nom or not brut_maj or not brut_valeur:
            # 4 658 par archive annuelle : des `<prix/>` sans aucun attribut.
            rejets.prix_malformes += 1
            continue
        try:
            carburant = depuis_nom_flux(nom).code
        except CarburantInconnu:
            rejets.carburants_inconnus += 1
            rejets.noter("carburant inconnu", nom)
            continue
        try:
            maj = lire_maj(brut_maj)
        except HorodatageIllisible:
            rejets.maj_illisibles += 1
            rejets.noter("horodatage illisible", brut_maj)
            continue
        try:
            prix = convertir_prix(float(brut_valeur))
        except ValueError:
            rejets.prix_malformes += 1
            rejets.noter("valeur illisible", brut_valeur)
            continue
        # Les memes bornes que pour le flux : hors bornes, ce n'est pas un prix.
        if not est_dans_les_bornes(carburant, prix):
            rejets.prix_hors_bornes += 1
            rejets.noter("prix hors bornes", f"{carburant} {prix}")
            continue
        yield PrixArchive(station_id=station_id, carburant=carburant, prix=prix, maj=maj)


def lire(
    chemin_zip: Path,
) -> tuple[Iterator[tuple[StationArchive, list[PrixArchive]]], RejetsArchive]:
    """Parcourt l'archive station par station, sans jamais tout charger en memoire.

    Rend l'iterateur **et** l'objet de comptage des rejets. Cet objet est le meme
    pendant toute la lecture : ses compteurs montent a mesure qu'on avance, et ne
    sont complets qu'une fois l'iterateur epuise.

    `element.clear()` apres chaque station est ce qui rend la chose possible : sans
    lui, `iterparse` garde l'arbre complet en memoire et 386 Mo de XML deviennent
    plusieurs gigaoctets.
    """
    rejets = RejetsArchive()

    def parcours() -> Iterator[tuple[StationArchive, list[PrixArchive]]]:
        with zipfile.ZipFile(chemin_zip) as archive:
            noms = archive.namelist()
            if not noms:
                raise ValueError(f"{chemin_zip} : archive vide")
            with archive.open(noms[0]) as flux:
                for evenement, element in iterparse(flux, events=("end",)):
                    if evenement != "end" or element.tag != "pdv":
                        continue
                    station = _station_depuis(element, rejets)
                    if station is not None:
                        yield station, list(_prix_depuis(element, station.station_id, rejets))
                    element.clear()

    return parcours(), rejets
