"""Telechargement de l'export complet du flux des prix.

On utilise `exports/` et non `records/` : ce dernier est pagine et plafonne a quelques
milliers d'enregistrements, ce qui le rend inadapte a un chargement complet. Le format
parquet est le plus leger des trois (2,8 Mo contre 3,2 en csv et 4,6 en json, mesure le
23/11/2026), mais le json est celui dont la structure est la plus fidele -- les champs
multivalues y sont de vraies listes.

Le fichier brut est ecrit sur disque, horodate et empreinte. Si son sha256 est
identique a celui de la collecte precedente, on ne cree pas de nouveau fichier :
inutile de garder douze copies identiques par heure.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx

from carburant_etl.config import URL_FLUX_EXPORT
from carburant_etl.fuseau import maintenant

TIMEOUT: Final = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
"""Timeouts explicites : jamais de requete qui pend indefiniment."""

TENTATIVES: Final = 4
"""Nombre total d'essais, avec un recul exponentiel entre chacun."""

RECUL_INITIAL: Final = 2.0
"""Secondes avant le premier reessai. Double a chaque fois : 2, 4, 8."""


class CollecteEchouee(RuntimeError):
    """Toutes les tentatives de telechargement ont echoue."""


@dataclass(frozen=True, slots=True)
class Collecte:
    """Resultat d'un telechargement, tel qu'il sera consigne dans `raw.collecte`."""

    source: str
    url: str
    debut: dt.datetime
    fin: dt.datetime
    octets: int
    sha256: str
    chemin: Path | None
    """`None` quand le contenu etait identique a la collecte precedente : le fichier
    n'a pas ete recree, mais la collecte a bien eu lieu."""
    inchange: bool

    @property
    def duree_secondes(self) -> float:
        return (self.fin - self.debut).total_seconds()


def _empreinte(donnees: bytes) -> str:
    return hashlib.sha256(donnees).hexdigest()


def nom_de_fichier(horodatage: dt.datetime, somme: str, prefixe: str = "flux-v2") -> str:
    """Nom d'un fichier brut : prefixe, horodatage a la seconde, debut de l'empreinte.

    L'empreinte fait partie du nom pour deux raisons. D'abord elle evite une collision :
    deux collectes dans la meme seconde -- cas d'un amorcage ou d'une relance manuelle --
    s'ecraseraient autrement l'une l'autre en silence. Ensuite elle permet de comparer
    le contenu sans decompresser quoi que ce soit.
    """
    return f"{prefixe}-{horodatage.strftime('%Y%m%dT%H%M%SZ')}-{somme[:12]}.json.gz"


def _derniere_empreinte(repertoire: Path, prefixe: str) -> str | None:
    """Empreinte du fichier le plus recent, lue dans son nom.

    Aucune decompression : le nom porte les douze premiers caracteres du sha256.
    """
    fichiers = sorted(repertoire.glob(f"{prefixe}-*.json.gz"))
    if not fichiers:
        return None
    return fichiers[-1].stem.removesuffix(".json").rsplit("-", 1)[-1]


def telecharger(
    repertoire: Path,
    *,
    user_agent: str,
    url: str = URL_FLUX_EXPORT,
    client: httpx.Client | None = None,
) -> Collecte:
    """Telecharge l'export complet et l'ecrit compresse sur disque.

    Le `User-Agent` identifie le projet et l'URL du depot : une source publique doit
    pouvoir savoir qui l'interroge et comment nous joindre.
    """
    repertoire.mkdir(parents=True, exist_ok=True)
    debut = maintenant()
    propre = client is None
    client = client or httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )

    try:
        donnees = _telecharger_avec_reessais(client, url)
    finally:
        if propre:
            client.close()

    fin = maintenant()
    somme = _empreinte(donnees)

    if _derniere_empreinte(repertoire, "flux-v2") == somme[:12]:
        return Collecte(
            source="flux-v2",
            url=url,
            debut=debut,
            fin=fin,
            octets=len(donnees),
            sha256=somme,
            chemin=None,
            inchange=True,
        )

    chemin = repertoire / nom_de_fichier(debut, somme)
    with gzip.open(chemin, "wb", compresslevel=6) as flux:
        flux.write(donnees)

    return Collecte(
        source="flux-v2",
        url=url,
        debut=debut,
        fin=fin,
        octets=len(donnees),
        sha256=somme,
        chemin=chemin,
        inchange=False,
    )


def _attendre(secondes: float) -> None:
    """Pause entre deux tentatives. Isolee pour pouvoir etre neutralisee en test."""
    time.sleep(secondes)


def _telecharger_avec_reessais(client: httpx.Client, url: str) -> bytes:
    """Telecharge, en reessayant avec un recul exponentiel.

    Seules les erreurs reseau et les codes HTTP d'erreur declenchent un reessai. Une
    reponse 4xx qui n'est pas 429 est reessayee elle aussi : si la source change d'URL
    ou de contrat, mieux vaut echouer franchement apres quatre essais qu'au premier,
    car un 404 passager existe aussi.
    """
    for tentative in range(TENTATIVES):
        try:
            reponse = client.get(url)
            reponse.raise_for_status()
        except httpx.HTTPError as erreur:
            if tentative == TENTATIVES - 1:
                raise CollecteEchouee(
                    f"{TENTATIVES} tentatives echouees sur {url} : {erreur}"
                ) from erreur
            _attendre(RECUL_INITIAL * 2**tentative)
        else:
            return reponse.content
    raise CollecteEchouee(f"{TENTATIVES} tentatives echouees sur {url}")


def purger(repertoire: Path, *, retention_jours: int, reference: dt.datetime | None = None) -> int:
    """Supprime les fichiers bruts plus vieux que la retention. Renvoie le compte.

    Les fichiers bruts servent a rejouer une transformation sans retelecharger ; passe
    un certain age ils ne servent plus a rien et occupent le disque du VPS.
    """
    if not repertoire.is_dir():
        return 0
    limite = (reference or maintenant()) - dt.timedelta(days=retention_jours)
    supprimes = 0
    for fichier in repertoire.glob("flux-v2-*.json.gz"):
        partie_date = fichier.name.removeprefix("flux-v2-").split("-", 1)[0]
        try:
            horodatage = dt.datetime.strptime(partie_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
        except ValueError:
            # Nom inattendu : on n'y touche pas plutot que de supprimer a l'aveugle.
            continue
        if horodatage < limite:
            fichier.unlink()
            supprimes += 1
    return supprimes


def copier_vers(collecte: Collecte, destination: Path) -> Path:
    """Copie un fichier brut, pour l'inspecter sans toucher a l'original."""
    if collecte.chemin is None:
        raise ValueError("cette collecte n'a pas cree de fichier (contenu inchange)")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(collecte.chemin, destination)
    return destination
