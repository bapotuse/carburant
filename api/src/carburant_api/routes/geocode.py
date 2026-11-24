"""`/v1/geocode` : proxy du geocodage de la Geoplateforme IGN.

Pourquoi un proxy alors que l'IGN autorise les appels directs depuis le navigateur
(`access-control-allow-origin: *`) : le quota est **partage**. Les en-tetes renvoyes
annoncent `ratelimit-limit: 50`. Un pic de trafic sur le site epuiserait le quota pour
tout le monde. Le cache de 24 heures et la limitation de debit sortante evitent cela,
et permettent au passage de restreindre la recherche a la France.

**La regle d'ambiguite est le coeur de cet endpoint.** Elle vient de quatre requetes
reelles (docs/reconnaissance.md section 4) :

| Requete | Score 1 | Ecart 1→2 | Decision |
|---|---|---|---|
| « 40 avenue du Prado, 13006 Marseille » | 0,972 | 0,517 | reponse directe |
| « 13008 » | 0,865 | 0,157 | reponse directe |
| « le Prado, Marseille » | 0,608 | 0,013 | demander de preciser |
| « Prado Marseille » | 0,708 | 0,009 | demander de preciser |

L'avenue du Prado existe dans deux arrondissements, a 1,2 km l'une de l'autre, avec
des scores qui different de 0,009 : il n'y a objectivement rien a deviner. Dans ce
cas on renvoie les candidats plutot que d'en choisir un au hasard.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Final

import httpx
from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel, Field

from carburant_api.cache import poser_entetes
from carburant_api.erreurs import BASE_TYPE, ProblemeAPI

routeur = APIRouter(tags=["geocodage"])

URL_GEOPLATEFORME: Final = "https://data.geopf.fr/geocodage/search"

SEUIL_SCORE: Final = 0.80
"""En dessous, meme le meilleur candidat n'est pas sur."""

ECART_MINIMAL: Final = 0.05
"""Deux candidats plus proches que cela ne se departagent pas."""

TYPES_UTILES: Final = ("housenumber", "street", "municipality", "locality")
"""Les tunnels et voies de liaison polluent les resultats : on garde ces quatre types
et on depriorise les `locality` dont le libelle commence par « Tunnel »."""

LIMITE_SORTANTE: Final = 5.0
"""Requetes par seconde vers l'IGN. Tres en dessous du quota annonce : on partage."""


class Candidat(BaseModel):
    """Un lieu propose par le geocodeur."""

    libelle: str = Field(examples=["40 Avenue du prado 13006 Marseille"])
    score: float = Field(ge=0, le=1, examples=[0.972])
    type: str = Field(
        description="`housenumber`, `street`, `municipality` ou `locality`.",
        examples=["housenumber"],
    )
    latitude: float = Field(examples=[43.283691])
    longitude: float = Field(examples=[5.384595])
    ville: str | None = Field(default=None, examples=["Marseille"])
    code_postal: str | None = Field(default=None, examples=["13006"])


class ReponseGeocode(BaseModel):
    """Resultat d'un geocodage, avec son verdict d'ambiguite."""

    requete: str = Field(description="Le texte demande.", examples=["le Prado, Marseille"])
    ambigu: bool = Field(
        description=(
            "Vrai quand le meilleur score est sous 0,80, ou quand les deux premiers "
            "candidats sont separes de moins de 0,05. Dans ce cas il faut **demander "
            "de preciser** plutot que de choisir : « le Prado » peut designer deux "
            "avenues distantes de 1,2 km."
        ),
        examples=[True],
    )
    raison: str | None = Field(
        default=None,
        description="Pourquoi la requete est jugee ambigue, en clair.",
        examples=["les deux premiers candidats sont separes de 0,013 point"],
    )
    candidats: list[Candidat] = Field(
        description="Classes par score decroissant, le meilleur d'abord."
    )


@dataclass(slots=True)
class _Cache:
    """Cache en memoire, avec expiration. Suffisant pour un seul processus.

    Un cache partage (Redis) serait necessaire si l'API tournait en plusieurs
    exemplaires. Ce n'est pas le cas sur un VPS a un seul conteneur, et ajouter un
    service pour cela serait une dependance de plus a justifier.
    """

    duree: float
    taille_max: int = 2000
    entrees: dict[str, tuple[float, ReponseGeocode]] = field(default_factory=dict)

    def lire(self, cle: str) -> ReponseGeocode | None:
        entree = self.entrees.get(cle)
        if entree is None:
            return None
        expire_le, valeur = entree
        if time.monotonic() > expire_le:
            del self.entrees[cle]
            return None
        return valeur

    def ecrire(self, cle: str, valeur: ReponseGeocode) -> None:
        if len(self.entrees) >= self.taille_max:
            # Purge simple : on vide les entrees expirees, et a defaut la plus
            # ancienne. Pas de LRU exact -- le gain ne vaut pas la complexite.
            maintenant = time.monotonic()
            expirees = [c for c, (fin, _) in self.entrees.items() if fin < maintenant]
            for c in expirees:
                del self.entrees[c]
            if len(self.entrees) >= self.taille_max:
                self.entrees.pop(next(iter(self.entrees)))
        self.entrees[cle] = (time.monotonic() + self.duree, valeur)


def _duree_cache() -> int:
    return int(os.environ.get("API_CACHE_GEOCODE_SECONDES", "86400"))


_cache: _Cache | None = None
_verrou_debit = asyncio.Lock()
_dernier_appel = 0.0


def cache() -> _Cache:
    """Le cache du processus, cree a la premiere utilisation."""
    global _cache
    if _cache is None:
        _cache = _Cache(duree=float(_duree_cache()))
    return _cache


async def _attendre_son_tour() -> None:
    """Espace les appels sortants vers l'IGN."""
    global _dernier_appel
    async with _verrou_debit:
        intervalle = 1.0 / LIMITE_SORTANTE
        attente = _dernier_appel + intervalle - time.monotonic()
        if attente > 0:
            await asyncio.sleep(attente)
        _dernier_appel = time.monotonic()


def _rang(candidat: dict[str, Any]) -> tuple[int, float]:
    """Cle de tri : les tunnels en dernier, puis le score decroissant."""
    libelle = str(candidat.get("libelle", ""))
    penalite = 1 if libelle.lower().startswith(("tunnel", "voie de liaison")) else 0
    return (penalite, -float(candidat.get("score", 0.0)))


def analyser(requete: str, bruts: list[dict[str, Any]]) -> ReponseGeocode:
    """Transforme la reponse de l'IGN en candidats, et tranche l'ambiguite.

    Fonction pure : c'est elle qui porte la regle, et elle se teste sans reseau.
    """
    candidats: list[Candidat] = []
    for trait in bruts:
        proprietes = trait.get("properties") or {}
        geometrie = trait.get("geometry") or {}
        coordonnees = geometrie.get("coordinates") or []
        if proprietes.get("type") not in TYPES_UTILES or len(coordonnees) < 2:
            continue
        candidats.append(
            Candidat(
                libelle=str(proprietes.get("label", "")),
                score=round(float(proprietes.get("score", 0.0)), 3),
                type=str(proprietes.get("type")),
                longitude=float(coordonnees[0]),
                latitude=float(coordonnees[1]),
                ville=proprietes.get("city"),
                code_postal=proprietes.get("postcode"),
            )
        )

    candidats.sort(key=lambda c: _rang({"libelle": c.libelle, "score": c.score}))

    if not candidats:
        return ReponseGeocode(
            requete=requete,
            ambigu=True,
            raison="aucun lieu trouve",
            candidats=[],
        )

    meilleur = candidats[0].score
    if meilleur < SEUIL_SCORE:
        return ReponseGeocode(
            requete=requete,
            ambigu=True,
            raison=f"le meilleur candidat ne marque que {meilleur:.3f}".replace(".", ","),
            candidats=candidats,
        )

    if len(candidats) > 1:
        # Arrondi a trois decimales, comme les scores eux-memes : sans cela,
        # `0,95 - 0,90` vaut 0,04999999999999993 en flottant et bascule du mauvais
        # cote de la borne. On compare ce qu'on affiche.
        ecart = round(meilleur - candidats[1].score, 3)
        if ecart < ECART_MINIMAL:
            return ReponseGeocode(
                requete=requete,
                ambigu=True,
                raison=(
                    f"les deux premiers candidats sont separes de {ecart:.3f}".replace(".", ",")
                    + " point"
                ),
                candidats=candidats,
            )

    return ReponseGeocode(requete=requete, ambigu=False, candidats=candidats)


@routeur.get(
    "/geocode",
    summary="Geocoder une adresse ou un lieu",
    description=(
        "Transforme un texte libre en coordonnees, via la Geoplateforme IGN, "
        "en se limitant a la France.\n\n"
        "**Le champ `ambigu` est le plus important de la reponse.** Quand il vaut "
        "`true`, il ne faut pas choisir le premier candidat : il faut demander de "
        "preciser. « le Prado » a Marseille designe deux avenues distantes de 1,2 km "
        "dont les scores different de 0,009 point.\n\n"
        "Les resultats sont mis en cache 24 heures."
    ),
    response_model=ReponseGeocode,
    responses={
        status.HTTP_502_BAD_GATEWAY: {
            "description": "Le geocodeur de l'IGN n'a pas repondu (problem+json)."
        }
    },
)
async def geocode(
    requete: Request,
    reponse: Response,
    q: Annotated[
        str,
        Query(
            min_length=2,
            max_length=200,
            description="Adresse, lieu, ville ou code postal.",
            examples=["le Prado, Marseille"],
        ),
    ],
    limite: Annotated[int, Query(ge=1, le=10, description="Nombre maximal de candidats.")] = 5,
) -> ReponseGeocode:
    """Geocode un texte libre, et dit franchement quand c'est ambigu."""
    cle = f"{q.strip().casefold()}|{limite}"
    en_cache = cache().lire(cle)
    if en_cache is not None:
        poser_entetes(reponse, en_cache, max_age=_duree_cache())
        reponse.headers["X-Cache"] = "HIT"
        return en_cache

    await _attendre_son_tour()
    client: httpx.AsyncClient = requete.app.state.client_http
    try:
        amont = await client.get(
            URL_GEOPLATEFORME,
            params={"q": q, "limit": limite, "index": "address"},
        )
        amont.raise_for_status()
        donnees = amont.json()
    except httpx.HTTPError as erreur:
        raise ProblemeAPI(
            statut=status.HTTP_502_BAD_GATEWAY,
            titre="Geocodeur indisponible",
            detail=(
                "Le service de geocodage de l'IGN n'a pas repondu. Reessayer dans "
                "quelques instants, ou utiliser des coordonnees directement."
            ),
            type_=f"{BASE_TYPE}#geocodeur-indisponible",
        ) from erreur

    resultat = analyser(q, donnees.get("features") or [])
    cache().ecrire(cle, resultat)
    poser_entetes(reponse, resultat, max_age=_duree_cache())
    reponse.headers["X-Cache"] = "MISS"
    return resultat
