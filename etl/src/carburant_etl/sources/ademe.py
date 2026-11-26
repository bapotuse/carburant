"""Facteurs d'emission par litre, depuis la Base Carbone de l'ADEME.

Le portail a migre d'Opendatasoft vers Data Fair : l'ancienne API Explore v2.1
repond HTTP 410. L'adresse utile est

    https://data.ademe.fr/data-fair/api/v1/datasets/base-carboner

**[verifie le 26/11/2026] Les noms de champs portent les accents** --
`Identifiant_de_l'élément`, `Nom_base_français`, `Unité_français`,
`Total_poste_non_décomposé` -- contrairement a ce que laissait entendre la
specification. Une requete avec les noms sans accents ne renvoie pas une erreur
JSON mais une page d'erreur : le piege est silencieux.

**Filtrer sur `Type_Ligne = "Elément"`.** Chaque element est accompagne de lignes
`Type_Ligne = "Poste"` qui portent sa decomposition amont / combustion. Les
additionner ferait compter le facteur deux fois.

Un meme element couvre parfois plusieurs carburants : l'element 25763
« Essence / Supercarburant sans plomb (95, 95-E10, 98) » vaut pour le SP95 et le
SP98. Le mapping est donc par carburant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

import httpx
from pydantic import BaseModel, Field, ValidationError

from carburant_etl.carburants import CodeCarburant

journal = logging.getLogger("carburant.ademe")

JEU: Final = "base-carboner"
RACINE: Final = "https://data.ademe.fr/data-fair/api/v1/datasets"
URL_JEU: Final = f"{RACINE}/{JEU}"
URL_LIGNES: Final = f"{URL_JEU}/lines"

ELEMENTS: Final[dict[CodeCarburant, str]] = {
    "gazole": "25775",  # Gazole routier / B7
    "sp95": "25763",  # Essence / Supercarburant sans plomb (95, 95-E10, 98)
    "sp98": "25763",  # le meme element couvre les trois supercarburants
    "e10": "13988",  # Essence / E10
    "e85": "25766",  # Essence / E85
    "gplc": "14031",  # GPL pour vehicule routier
}
"""Carburant -> identifiant de l'element ADEME. Verifie le 26/11/2026."""

UNITE_ATTENDUE: Final = "kgCO2e/litre"

ORDRES_DE_GRANDEUR: Final[dict[CodeCarburant, float]] = {
    "gazole": 3.1,
    "sp95": 2.69,
    "sp98": 2.69,
    "e10": 2.69,
    "e85": 1.11,
    "gplc": 1.86,
}
"""Pour **controle de coherence seulement**, jamais comme valeur affichee.

Un ecart de plus de 20 % veut dire que l'unite a change (par kilogramme ? par
megajoule ?) ou que l'element ne designe plus la meme chose. Dans les deux cas il
faut regarder avant de publier un chiffre d'empreinte carbone.
"""

ECART_TOLERE: Final = 0.20

CHAMPS: Final = (
    "Identifiant_de_l'élément",
    "Type_Ligne",
    "Statut_de_l'élément",
    "Nom_base_français",
    "Nom_attribut_français",
    "Unité_français",
    "Total_poste_non_décomposé",
    "Localisation_géographique",
    "Date_de_modification",
    "Période_de_validité",
)

TIMEOUT: Final = httpx.Timeout(connect=15.0, read=60.0, write=15.0, pool=15.0)


class ElementCarbone(BaseModel):
    """Une ligne « Elément » de la Base Carbone, telle que l'API la rend."""

    identifiant: str = Field(alias="Identifiant_de_l'élément")
    type_ligne: str = Field(alias="Type_Ligne")
    statut: str | None = Field(default=None, alias="Statut_de_l'élément")
    nom_base: str = Field(alias="Nom_base_français")
    nom_attribut: str | None = Field(default=None, alias="Nom_attribut_français")
    unite: str = Field(alias="Unité_français")
    valeur: float = Field(alias="Total_poste_non_décomposé")
    localisation: str | None = Field(default=None, alias="Localisation_géographique")
    date_modification: str | None = Field(default=None, alias="Date_de_modification")
    periode_validite: str | None = Field(default=None, alias="Période_de_validité")

    model_config = {"populate_by_name": True}


@dataclass(frozen=True, slots=True)
class Facteur:
    """Un facteur d'emission pret a etre historise."""

    carburant: CodeCarburant
    element_ademe: str
    nom_base: str
    nom_attribut: str | None
    valeur: float
    unite: str
    localisation: str | None
    statut: str | None
    date_modification: str | None
    periode_validite: str | None
    version_base: str
    url: str


class SourceIncoherente(RuntimeError):
    """La source a change de nature : unite differente, ecart trop grand, absence."""


def _client(user_agent: str) -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
        follow_redirects=True,
    )


def version_du_jeu(client: httpx.Client) -> str:
    """`updatedAt` du jeu : le seul reperage de version dont on dispose.

    La Base Carbone n'expose aucun numero de version. On garde donc la date de
    derniere modification du jeu, qui joue ce role.
    """
    reponse = client.get(URL_JEU)
    reponse.raise_for_status()
    corps: dict[str, Any] = reponse.json()
    version = corps.get("updatedAt")
    if not isinstance(version, str) or not version:
        raise SourceIncoherente(f"le jeu ADEME ne donne pas de updatedAt exploitable : {version!r}")
    return version


def lire_element(client: httpx.Client, identifiant: str) -> ElementCarbone:
    """Recupere l'unique ligne « Elément » d'un identifiant."""
    reponse = client.get(
        URL_LIGNES,
        params={
            "qs": f'Identifiant_de_l\'élément:"{identifiant}"',
            "size": 20,
            "select": ",".join(CHAMPS),
        },
    )
    reponse.raise_for_status()
    resultats = reponse.json().get("results", [])

    elements: list[ElementCarbone] = []
    for brut in resultats:
        if brut.get("Type_Ligne") != "Elément":
            # Les lignes « Poste » portent la decomposition amont / combustion :
            # les additionner compterait le facteur deux fois.
            continue
        try:
            elements.append(ElementCarbone.model_validate(brut))
        except ValidationError as erreur:
            raise SourceIncoherente(
                f"element {identifiant} : ligne illisible ({erreur.error_count()} champ(s))"
            ) from erreur

    if len(elements) != 1:
        raise SourceIncoherente(
            f"element {identifiant} : {len(elements)} ligne(s) de type Element, une attendue"
        )
    return elements[0]


def verifier(carburant: CodeCarburant, element: ElementCarbone) -> None:
    """Refuse un facteur dont l'unite ou l'ordre de grandeur a change.

    Ce controle est la raison d'etre d'`ORDRES_DE_GRANDEUR`. Publier « votre plein
    emet 31 kg de CO2 » au lieu de 3,1 parce que l'ADEME est passee au kilogramme
    serait une erreur invisible dans le code et grossiere a l'ecran.
    """
    if element.unite != UNITE_ATTENDUE:
        raise SourceIncoherente(
            f"{carburant} : unite « {element.unite} » au lieu de « {UNITE_ATTENDUE} ». "
            "Verifier le perimetre avant de publier quoi que ce soit."
        )
    attendu = ORDRES_DE_GRANDEUR[carburant]
    ecart = abs(element.valeur - attendu) / attendu
    if ecart > ECART_TOLERE:
        raise SourceIncoherente(
            f"{carburant} : {element.valeur} {element.unite}, soit {ecart:.0%} d ecart avec "
            f"l ordre de grandeur connu ({attendu}). Verifier l unite et le perimetre."
        )
    if ecart > 0:
        journal.info(
            "%s : %.3f %s (%.1f %% d ecart avec l ordre de grandeur connu)",
            carburant,
            element.valeur,
            element.unite,
            ecart * 100,
        )


def recuperer(user_agent: str) -> list[Facteur]:
    """Recupere les six facteurs, verifies. Leve si la source a change de nature."""
    facteurs: list[Facteur] = []
    with _client(user_agent) as client:
        version = version_du_jeu(client)
        journal.info("Base Carbone ADEME, version du jeu : %s", version)
        # Un meme element sert plusieurs carburants : on ne le telecharge qu'une fois.
        cache: dict[str, ElementCarbone] = {}
        for carburant, identifiant in ELEMENTS.items():
            if identifiant not in cache:
                cache[identifiant] = lire_element(client, identifiant)
            element = cache[identifiant]
            verifier(carburant, element)
            facteurs.append(
                Facteur(
                    carburant=carburant,
                    element_ademe=element.identifiant,
                    nom_base=element.nom_base,
                    nom_attribut=element.nom_attribut,
                    valeur=element.valeur,
                    unite=element.unite,
                    localisation=element.localisation,
                    statut=element.statut,
                    date_modification=element.date_modification,
                    periode_validite=element.periode_validite,
                    version_base=version,
                    url=f"{URL_LIGNES}?qs=Identifiant_de_l%27%C3%A9l%C3%A9ment%3A%22{identifiant}%22",
                )
            )
    return facteurs
