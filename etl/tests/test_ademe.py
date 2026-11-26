"""Facteurs d'emission : lecture de la Base Carbone et historisation.

Le test le plus important est `test_une_unite_differente_est_refusee` : publier
« votre plein emet 31 kg de CO2 » au lieu de 3,1 parce que l'ADEME serait passee au
kilogramme serait invisible dans le code et grossier a l'ecran.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import psycopg
import pytest
from carburant_etl.carburants import CodeCarburant
from carburant_etl.chargement.facteurs import charger
from carburant_etl.chargement.migrations import appliquer
from carburant_etl.chargement.staging import ouvrir
from carburant_etl.sources import ademe

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")


def element(**surcharges: Any) -> ademe.ElementCarbone:
    defauts: dict[str, Any] = {
        "Identifiant_de_l'élément": "25775",
        "Type_Ligne": "Elément",
        "Statut_de_l'élément": "Valide générique",
        "Nom_base_français": "Gazole routier",
        "Nom_attribut_français": "B7",
        "Unité_français": "kgCO2e/litre",
        "Total_poste_non_décomposé": 3.1,
        "Localisation_géographique": "France continentale",
        "Date_de_modification": "2021-06-18",
        "Période_de_validité": "déc-20",
    }
    defauts.update(surcharges)
    return ademe.ElementCarbone.model_validate(defauts)


# ------------------------------------------------------------------ le controle
def test_les_valeurs_connues_passent_le_controle() -> None:
    ademe.verifier("gazole", element())


def test_une_unite_differente_est_refusee() -> None:
    """Par kilogramme au lieu de par litre : le chiffre serait faux d'un facteur 1000."""
    with pytest.raises(ademe.SourceIncoherente, match="unite"):
        ademe.verifier("gazole", element(**{"Unité_français": "kgCO2e/kg"}))


@pytest.mark.parametrize("valeur", [3.1 * 1.25, 3.1 * 0.75])
def test_un_ecart_de_plus_de_20_pourcent_est_refuse(valeur: float) -> None:
    with pytest.raises(ademe.SourceIncoherente, match="ecart"):
        ademe.verifier("gazole", element(**{"Total_poste_non_décomposé": valeur}))


def test_un_ecart_modere_passe() -> None:
    """L'ADEME peut reviser un facteur de quelques pour cent : ce n'est pas une panne."""
    ademe.verifier("gazole", element(**{"Total_poste_non_décomposé": 3.1 * 1.15}))


def test_les_ordres_de_grandeur_couvrent_les_six_carburants() -> None:
    """Un carburant sans ordre de grandeur passerait le controle sans etre verifie."""
    assert set(ademe.ORDRES_DE_GRANDEUR) == set(ademe.ELEMENTS)


def test_un_element_couvre_plusieurs_carburants() -> None:
    """25763 vaut pour le SP95 et le SP98 : le mapping est par carburant, pas par element."""
    assert ademe.ELEMENTS["sp95"] == ademe.ELEMENTS["sp98"] == "25763"


# ------------------------------------------------------------------ la lecture
def reponse_avec(lignes: list[dict[str, Any]]) -> httpx.Client:
    """Un client qui rend ces lignes, sans toucher au reseau."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": len(lignes), "results": lignes})

    return httpx.Client(transport=httpx.MockTransport(gestionnaire))


def test_les_lignes_poste_sont_ignorees() -> None:
    """Additionner les postes compterait le facteur deux fois : amont + combustion."""
    lignes = [
        {
            "Identifiant_de_l'élément": "25775",
            "Type_Ligne": "Poste",
            "Nom_base_français": "Gazole routier",
            "Unité_français": "kgCO2e/litre",
            "Total_poste_non_décomposé": 2.49,
        },
        {
            "Identifiant_de_l'élément": "25775",
            "Type_Ligne": "Poste",
            "Nom_base_français": "Gazole routier",
            "Unité_français": "kgCO2e/litre",
            "Total_poste_non_décomposé": 0.609,
        },
        {
            "Identifiant_de_l'élément": "25775",
            "Type_Ligne": "Elément",
            "Nom_base_français": "Gazole routier",
            "Nom_attribut_français": "B7",
            "Unité_français": "kgCO2e/litre",
            "Total_poste_non_décomposé": 3.1,
        },
    ]
    with reponse_avec(lignes) as client:
        lu = ademe.lire_element(client, "25775")
    assert lu.valeur == 3.1, (
        "la valeur retenue doit etre celle de l element, pas la somme des postes"
    )


def test_aucun_element_trouve_leve() -> None:
    with reponse_avec([]) as client, pytest.raises(ademe.SourceIncoherente, match="0 ligne"):
        ademe.lire_element(client, "99999")


def test_plusieurs_elements_levent() -> None:
    """Deux elements pour un identifiant : on ne devine pas lequel est le bon."""
    ligne = {
        "Identifiant_de_l'élément": "25775",
        "Type_Ligne": "Elément",
        "Nom_base_français": "Gazole routier",
        "Unité_français": "kgCO2e/litre",
        "Total_poste_non_décomposé": 3.1,
    }
    with reponse_avec([ligne, ligne]) as client, pytest.raises(ademe.SourceIncoherente):
        ademe.lire_element(client, "25775")


# ------------------------------------------------------------- l'historisation
@pytest.fixture
def base() -> Iterator[str]:
    assert URL
    nom = f"carburant_ademe_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(URL, autocommit=True) as administration:
        administration.execute(f'CREATE DATABASE "{nom}"')
    url_test = URL.rsplit("/", 1)[0] + f"/{nom}"
    try:
        appliquer(url_test)
        yield url_test
    finally:
        with psycopg.connect(URL, autocommit=True) as administration:
            administration.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nom,),
            )
            administration.execute(f'DROP DATABASE IF EXISTS "{nom}"')


def facteur(
    carburant: CodeCarburant = "gazole", version: str = "2026-06-30T10:17:08.470Z"
) -> ademe.Facteur:
    return ademe.Facteur(
        carburant=carburant,
        element_ademe="25775",
        nom_base="Gazole routier",
        nom_attribut="B7",
        valeur=3.1,
        unite="kgCO2e/litre",
        localisation="France continentale",
        statut="Valide générique",
        date_modification="2021-06-18",
        periode_validite="déc-20",
        version_base=version,
        url="https://data.ademe.fr/...",
    )


@pytest.mark.integration
@sans_base
def test_recharger_la_meme_version_ne_cree_pas_de_doublon(base: str) -> None:
    connexion = ouvrir(base)
    try:
        premier = charger(connexion, [facteur()])
        second = charger(connexion, [facteur()])
        with connexion.cursor() as curseur:
            curseur.execute("SELECT count(*) FROM marts.ref_facteur_emission")
            total = curseur.fetchone()
    finally:
        connexion.close()
    assert premier.nouveaux == 1
    assert second.nouveaux == 0 and second.deja_connus == 1
    assert total is not None and total[0] == 1


@pytest.mark.integration
@sans_base
def test_une_nouvelle_version_ajoute_une_ligne_sans_effacer_l_ancienne(base: str) -> None:
    """Un chiffre publie doit rester explicable six mois plus tard."""
    connexion = ouvrir(base)
    try:
        charger(connexion, [facteur(version="2025-01-01T00:00:00.000Z")])
        charger(connexion, [facteur(version="2026-06-30T10:17:08.470Z")])
        with connexion.cursor() as curseur:
            curseur.execute("SELECT count(*) FROM marts.ref_facteur_emission")
            total = curseur.fetchone()
            curseur.execute("SELECT version_base FROM marts.facteur_emission_courant")
            courant = curseur.fetchone()
    finally:
        connexion.close()
    assert total is not None and total[0] == 2, "l ancienne version doit rester"
    assert courant is not None and courant[0] == "2026-06-30T10:17:08.470Z"


# ------------------------------------------------------------- la vraie source
@pytest.mark.reseau
def test_la_vraie_base_carbone_repond_ce_qu_on_attend() -> None:
    """Contre l'API reelle de l'ADEME.

    Verifie ce qu'aucun bouchon ne peut verifier : que les noms de champs accentues
    sont les bons, que les six elements existent toujours, et que leurs valeurs
    restent dans les ordres de grandeur connus.
    """
    facteurs = ademe.recuperer("carburant/tests (+https://github.com/bapotuse/carburant)")
    assert len(facteurs) == len(ademe.ELEMENTS)
    par_carburant = {f.carburant: f for f in facteurs}
    for carburant, attendu in ademe.ORDRES_DE_GRANDEUR.items():
        obtenu = par_carburant[carburant]
        assert obtenu.unite == ademe.UNITE_ATTENDUE
        assert abs(obtenu.valeur - attendu) / attendu <= ademe.ECART_TOLERE
        assert obtenu.version_base, "la version du jeu doit etre renseignee"
