"""Enseignes des stations, depuis OpenStreetMap par l'API Overpass.

Le flux officiel ne contient ni nom ni enseigne : aucun de ses 47 champs. OSM, lui,
en a — et bien mieux que prevu.

**Le constat qui a change le plan** (reconnaissance du 26/11/2026, `docs/
reconnaissance.md` § 6). La specification prevoyait un rapprochement *spatial*. Or
sur les 12 610 points `amenity=fuel` de France, **10 146 portent le tag
`ref:FR:prix-carburants`, soit 80,5 %** — c'est l'identifiant de station du flux que
nous collectons. Pour ces stations, le rapprochement est une jointure sur cle. Le
spatial ne sert que pour le reliquat.

**Second constat : `brand:wikidata` unifie les variantes de marque.** Les libelles
eclatent une meme enseigne — TotalEnergies 1 209, Total 1 078, Total Access 405 —
alors que `brand:wikidata = Q154037` en compte 2 674, soit leur somme. Un classement
bati sur le libelle compterait Total trois fois ; il se construira sur l'identifiant.

**L'instance Overpass est capricieuse.** Injoignable depuis l'environnement de
developpement, elle a aussi refuse une premiere tentative depuis un runner GitHub
avant d'accepter la seconde, deux minutes plus tard. D'ou les reessais et la liste de
miroirs.

Licence **ODbL** : l'attribution d'OpenStreetMap est obligatoire partout ou une
enseigne est affichee.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx

journal = logging.getLogger("carburant.osm")

MIROIRS: Final[tuple[str, ...]] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
"""Essayes dans l'ordre. Le premier qui repond gagne."""

REQUETE: Final = """
[out:json][timeout:600];
area["ISO3166-1"="FR"][admin_level=2]->.fr;
nwr["amenity"="fuel"](area.fr);
out center tags;
"""

CLE_REFERENCE: Final = "ref:FR:prix-carburants"
"""Le tag qui porte l'identifiant officiel. 80,5 % des stations OSM l'ont."""

TENTATIVES_PAR_MIROIR: Final = 2
RECUL_SECONDES: Final = 20.0

# La reponse fait 7,7 Mo et met une centaine de secondes a venir : le `read` doit
# etre large, et le `connect` court pour passer vite au miroir suivant.
TIMEOUT: Final = httpx.Timeout(connect=20.0, read=900.0, write=30.0, pool=20.0)

ATTENDUS_MINIMUM: Final = 8_000
"""En dessous, la reponse est tronquee ou la requete a change de sens.

Mesure du 26/11/2026 : 12 610 elements. Un seuil a 8 000 laisse de la marge pour les
variations normales d'OSM tout en attrapant une reponse partielle.
"""


class SourceOsmIndisponible(RuntimeError):
    """Aucun miroir n'a rendu de reponse exploitable."""


@dataclass(frozen=True, slots=True)
class PointOsm:
    """Un point `amenity=fuel`, reduit a ce dont on se sert."""

    type_osm: str
    id_osm: int
    longitude: float
    latitude: float
    reference_officielle: str | None
    """`ref:FR:prix-carburants` : l'identifiant de station du flux, quand il y est."""
    enseigne: str | None
    wikidata: str | None

    @property
    def cle(self) -> str:
        """L'identifiant OSM complet, par exemple `node/144574`."""
        return f"{self.type_osm}/{self.id_osm}"


def _enseigne_de(tags: dict[str, str]) -> str | None:
    """Le libelle d'enseigne, par ordre de fiabilite decroissante.

    `brand` d'abord (85,9 % des points) : c'est le tag fait pour cela. `name`
    ensuite, qui vaut souvent l'enseigne (« Intermarche ») mais parfois la station
    (« Relais Beaune Tailly (PL) »). `operator` en dernier (34,8 %), qui designe
    l'exploitant et pas toujours l'enseigne.
    """
    for cle in ("brand", "name", "operator"):
        valeur = (tags.get(cle) or "").strip()
        if valeur:
            return valeur
    return None


def _position_de(element: dict[str, Any]) -> tuple[float, float] | None:
    """Longitude et latitude, que l'element soit un point ou une surface.

    `out center` donne un centre aux `way` et aux `relation` ; mesure du 26/11/2026 :
    **aucun** des 12 610 elements n'est sans position.
    """
    if "lon" in element and "lat" in element:
        return float(element["lon"]), float(element["lat"])
    centre = element.get("center")
    if isinstance(centre, dict) and "lon" in centre and "lat" in centre:
        return float(centre["lon"]), float(centre["lat"])
    return None


def lire_elements(elements: list[dict[str, Any]]) -> list[PointOsm]:
    """Convertit la reponse Overpass en points exploitables.

    Un element sans position ni enseigne ni reference n'apporte rien : il est ecarte
    en silence, ce n'est pas une anomalie mais une station qu'OSM connait mal.
    """
    points: list[PointOsm] = []
    for element in elements:
        position = _position_de(element)
        if position is None:
            continue
        tags = element.get("tags") or {}
        reference = (tags.get(CLE_REFERENCE) or "").strip() or None
        enseigne = _enseigne_de(tags)
        if reference is None and enseigne is None:
            continue
        points.append(
            PointOsm(
                type_osm=str(element.get("type", "node")),
                id_osm=int(element["id"]),
                longitude=position[0],
                latitude=position[1],
                reference_officielle=reference,
                enseigne=enseigne,
                wikidata=(tags.get("brand:wikidata") or "").strip() or None,
            )
        )
    return points


def recuperer(
    user_agent: str,
    *,
    miroirs: tuple[str, ...] = MIROIRS,
    client: httpx.Client | None = None,
) -> list[PointOsm]:
    """Interroge Overpass et rend les points exploitables.

    Essaie chaque miroir deux fois avant de passer au suivant : l'instance principale
    refuse parfois une connexion puis accepte la suivante.

    `client` permet aux tests de fournir un transport sans toucher au reseau. En
    production il reste `None` : la fonction ouvre le sien et le referme.
    """
    entetes = {"User-Agent": user_agent, "Accept": "application/json"}
    fourni = client is not None
    client = client or httpx.Client(timeout=TIMEOUT, headers=entetes, follow_redirects=True)
    try:
        return _interroger(client, miroirs)
    finally:
        if not fourni:
            client.close()


def _interroger(client: httpx.Client, miroirs: tuple[str, ...]) -> list[PointOsm]:
    """Boucle sur les miroirs et les tentatives. Leve si aucun ne repond."""
    dernier_echec = ""
    for miroir in miroirs:
        for tentative in range(1, TENTATIVES_PAR_MIROIR + 1):
            try:
                reponse = client.post(miroir, data={"data": REQUETE})
                reponse.raise_for_status()
                elements = reponse.json().get("elements", [])
            except (httpx.HTTPError, ValueError) as erreur:
                dernier_echec = f"{miroir} : {type(erreur).__name__}"
                journal.warning(
                    "overpass %s, tentative %d/%d : %s",
                    miroir,
                    tentative,
                    TENTATIVES_PAR_MIROIR,
                    erreur,
                )
                if tentative < TENTATIVES_PAR_MIROIR:
                    time.sleep(RECUL_SECONDES)
                continue

            if len(elements) < ATTENDUS_MINIMUM:
                # Une reponse courte n'est pas une reponse : Overpass tronque sans
                # rien dire quand il est charge.
                dernier_echec = f"{miroir} : {len(elements)} elements seulement"
                journal.warning(
                    "overpass %s : %d elements, moins que les %d attendus",
                    miroir,
                    len(elements),
                    ATTENDUS_MINIMUM,
                )
                continue

            points = lire_elements(elements)
            journal.info(
                "overpass %s : %d elements, %d exploitables, %d avec reference officielle",
                miroir,
                len(elements),
                len(points),
                sum(1 for p in points if p.reference_officielle),
            )
            return points

    raise SourceOsmIndisponible(f"aucun miroir Overpass exploitable ({dernier_echec})")
