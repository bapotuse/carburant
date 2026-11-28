"""Les six outils, vus par un vrai client MCP.

Ces tests passent par le protocole : initialisation, `list_tools`, `call_tool`. Ce
qu'ils vérifient n'est donc pas « ma fonction renvoie le bon dictionnaire » mais « un
assistant branché sur ce serveur reçoit la bonne réponse », ce qui n'est pas la même
chose — un schéma d'entrée mal déduit ou une sortie structurée invalide ne se voient
que de ce côté-là.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest

from mcp import ClientSession

Fabrique = Callable[[dict[str, dict[str, Any]]], httpx.AsyncClient]
Session = Callable[[httpx.AsyncClient], AbstractAsyncContextManager[ClientSession]]
Charges = dict[str, dict[str, Any]]


def _texte(resultat: Any) -> str:
    """Le texte renvoyé par un outil, concaténé."""
    return "\n".join(
        bloc.text for bloc in resultat.content if getattr(bloc, "type", None) == "text"
    )


def _structure(resultat: Any) -> dict[str, Any]:
    """La sortie structurée d'un outil."""
    assert resultat.structured_content is not None, "l'outil doit rendre une sortie structuree"
    charge: dict[str, Any] = resultat.structured_content
    return charge


# ------------------------------------------------------------------ le catalogue
async def test_les_six_outils_sont_annonces(api: Fabrique, ouvrir: Session) -> None:
    async with ouvrir(api({})) as cliente:
        outils = (await cliente.list_tools()).tools
    noms = sorted(outil.name for outil in outils)
    assert noms == [
        "comparer_carburants",
        "empreinte_carbone_plein",
        "meilleure_station_avec_autonomie",
        "prix_station",
        "tendance_prix",
        "trouver_station_moins_chere",
    ]


async def test_chaque_outil_est_annote_en_lecture_seule(api: Fabrique, ouvrir: Session) -> None:
    """Un client doit pouvoir appeler ces outils sans demander d'autorisation.

    Aucun ne modifie quoi que ce soit : ils lisent une API publique.
    """
    async with ouvrir(api({})) as cliente:
        outils = (await cliente.list_tools()).tools
    for outil in outils:
        assert outil.annotations is not None, f"{outil.name} n'est pas annote"
        assert outil.annotations.read_only_hint is True, f"{outil.name} n'est pas en lecture seule"


async def test_chaque_outil_dit_quand_le_choisir(api: Fabrique, ouvrir: Session) -> None:
    """Une description d'outil est lue par un modele, pas par un humain.

    Si elle ne dit pas **quand** choisir cet outil plutot qu'un autre, il sera appele
    au mauvais moment et la reponse paraitra fausse alors qu'elle sera juste.
    """
    async with ouvrir(api({})) as cliente:
        outils = (await cliente.list_tools()).tools
    for outil in outils:
        description = outil.description or ""
        assert len(description) > 200, f"{outil.name} : description trop courte pour servir"
        assert "Choisis cet outil" in description, (
            f"{outil.name} ne dit pas quand le choisir plutot qu'un autre"
        )


async def test_les_instructions_du_serveur_portent_la_regle_de_la_date(
    api: Fabrique, ouvrir: Session
) -> None:
    """La regle la plus importante du projet doit etre lue avant la premiere question."""
    async with ouvrir(api({})) as cliente:
        resultat = await cliente.initialize()
    instructions = resultat.instructions or ""
    assert "date" in instructions.lower()
    assert "ambigu" in instructions.lower()
    assert "ADEME" in instructions


# -------------------------------------------------- trouver_station_moins_chere
async def test_trouver_rend_les_stations_les_moins_cheres_avec_leur_date(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    client = api(
        {"/v1/geocode": charges["geocode_precis"], "/v1/stations/proches": charges["proches"]}
    )
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "trouver_station_moins_chere",
            {"lieu": "40 avenue du Prado, 13006 Marseille", "carburant": "diesel"},
        )
    assert not resultat.is_error, _texte(resultat)
    structure = _structure(resultat)
    assert structure["carburant"] == "gazole", "« diesel » doit etre normalise"
    assert structure["carburant_libelle"] == "gazole"
    assert structure["stations"], "la reponse doit contenir des stations"

    premiere = structure["stations"][0]
    assert premiere["prix_affiche"].endswith("€/L"), "le prix doit etre au format francais"
    assert "," in premiere["prix_affiche"], "virgule decimale attendue"
    assert premiere["maj_affichee"], "un prix sans sa date devient faux en silence"
    assert premiere["itineraires"]["waze"].startswith("https://waze.com/ul?ll=")

    prix = [station["prix_eur_l"] for station in structure["stations"]]
    assert prix == sorted(prix), "les moins cheres d'abord"
    assert premiere["prix_affiche"] in _texte(resultat)


async def test_trouver_refuse_une_adresse_ambigue_en_listant_les_candidats(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    """L'avenue du Prado existe en 13006 et 13008, sans station en commun."""
    client = api({"/v1/geocode": charges["geocode_ambigu"]})
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "trouver_station_moins_chere",
            {"lieu": "le Prado, Marseille", "carburant": "gazole"},
        )
    assert resultat.is_error, "une adresse ambigue ne doit pas etre tranchee par le serveur"
    message = _texte(resultat)
    assert "13006" in message and "13008" in message, "le refus doit nommer les candidats"
    assert "Demande lequel" in message


async def test_trouver_refuse_un_carburant_ambigu(api: Fabrique, ouvrir: Session) -> None:
    """« Super » a designe le 98 plombe puis le 95 : deviner afficherait un prix faux."""
    async with ouvrir(api({})) as cliente:
        resultat = await cliente.call_tool(
            "trouver_station_moins_chere", {"lieu": "Marseille", "carburant": "super"}
        )
    assert resultat.is_error
    message = _texte(resultat)
    assert "sp95" in message and "sp98" in message


async def test_trouver_liste_les_valeurs_acceptees_pour_un_carburant_inconnu(
    api: Fabrique, ouvrir: Session
) -> None:
    async with ouvrir(api({})) as cliente:
        resultat = await cliente.call_tool(
            "trouver_station_moins_chere", {"lieu": "Marseille", "carburant": "kerosene"}
        )
    assert resultat.is_error
    message = _texte(resultat)
    for code in ("gazole", "sp95", "e10", "sp98", "e85", "gplc"):
        assert code in message


async def test_trouver_le_dit_quand_aucune_station_ne_vend_ce_carburant(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    vide = {"stations": [], "total": 0, "rayon_km": 5.0, "carburant": "gplc", "tri": "prix"}
    client = api({"/v1/geocode": charges["geocode_precis"], "/v1/stations/proches": vide})
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "trouver_station_moins_chere",
            {"lieu": "40 avenue du Prado, 13006 Marseille", "carburant": "GPL"},
        )
    assert not resultat.is_error, _texte(resultat)
    assert _structure(resultat)["stations"] == []
    texte = _texte(resultat)
    assert "Aucune station" in texte
    assert "rayon plus" in texte, "un etat vide doit suggerer quoi faire ensuite"


# ------------------------------------------- meilleure_station_avec_autonomie
async def test_la_meilleure_station_rend_le_cout_reel_et_ses_hypotheses(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    client = api(
        {"/v1/geocode": charges["geocode_precis"], "/v1/stations/meilleure": charges["meilleure"]}
    )
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "meilleure_station_avec_autonomie",
            {
                "lieu": "40 avenue du Prado, 13006 Marseille",
                "carburant": "gazole",
                "autonomie_km": 60,
            },
        )
    assert not resultat.is_error, _texte(resultat)
    structure = _structure(resultat)
    assert structure["meilleure"] is not None
    assert structure["hypotheses"], "le calcul doit dire ce qu'il suppose"
    assert "facteur_detour" in structure["hypotheses"]
    assert structure["economie_eur"] >= 0, "l'economie ne peut pas etre negative"

    texte = _texte(resultat)
    assert "détour" in texte or "detour" in texte, "l'hypothese du detour doit etre dite"
    assert structure["meilleure"]["prix_affiche"] in texte


async def test_la_meilleure_station_relaie_l_avertissement_quand_rien_n_est_atteignable(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    """Proposer une station hors de portee serait le pire resultat possible."""
    rien = {
        "meilleure": None,
        "la_plus_proche": None,
        "economie_eur": 0.0,
        "stations": [],
        "atteignables": 0,
        "avertissement": "Aucune station atteignable avec 5 km d'autonomie.",
        "hypotheses": charges["meilleure"]["hypotheses"],
    }
    client = api({"/v1/geocode": charges["geocode_precis"], "/v1/stations/meilleure": rien})
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "meilleure_station_avec_autonomie",
            {
                "lieu": "40 avenue du Prado, 13006 Marseille",
                "carburant": "gazole",
                "autonomie_km": 5,
            },
        )
    assert not resultat.is_error, _texte(resultat)
    assert _structure(resultat)["meilleure"] is None
    assert "Aucune station atteignable" in _texte(resultat)


async def test_une_autonomie_negative_est_refusee_par_le_schema(
    api: Fabrique, ouvrir: Session
) -> None:
    """Le schema d'entree doit faire ce travail, pas le code de l'outil."""
    async with ouvrir(api({})) as cliente:
        resultat = await cliente.call_tool(
            "meilleure_station_avec_autonomie",
            {"lieu": "Marseille", "carburant": "gazole", "autonomie_km": -10},
        )
    assert resultat.is_error


# ------------------------------------------------------------------ prix_station
async def test_prix_station_par_identifiant_ne_cache_rien(api: Fabrique, ouvrir: Session) -> None:
    """Une fiche montre les prix perimes et les ruptures, contrairement a une recherche."""
    fiche = {
        "id": 13008003,
        "enseigne": "TotalEnergies",
        "adresse": "32 BOULEVARD SCHLOESING",
        "ville": "Marseille",
        "cp": "13008",
        "departement": "Bouches-du-Rhône",
        "code_departement": "13",
        "region": "Provence-Alpes-Côte d'Azur",
        "autoroute": False,
        "latitude": 43.272,
        "longitude": 5.393,
        "active": True,
        "premiere_vue": "2026-11-23T10:00:00Z",
        "derniere_vue": "2026-11-28T10:00:00Z",
        "services": ["Station de lavage"],
        "horaires": None,
        "prix": [
            {
                "carburant": "gazole",
                "prix_eur_l": 1.879,
                "maj": "2026-11-28T06:00:00Z",
                "fraicheur": "frais",
                "rupture": None,
            },
            {
                "carburant": "e85",
                "prix_eur_l": 0.869,
                "maj": "2026-08-01T06:00:00Z",
                "fraicheur": "perime",
                "rupture": None,
            },
            {
                "carburant": "gplc",
                "prix_eur_l": None,
                "maj": None,
                "fraicheur": None,
                "rupture": "annonce_sans_prix",
            },
        ],
    }
    client = api({"/v1/stations/13008003": fiche})
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool("prix_station", {"station": "13008003"})
    assert not resultat.is_error, _texte(resultat)
    structure = _structure(resultat)
    assert structure["distance_de_l_adresse_km"] is None, "trouvee par identifiant, pas par adresse"
    codes = {entree["carburant"] for entree in structure["prix"]}
    assert codes == {"gazole", "e85", "gplc"}

    texte = _texte(resultat)
    assert "périmé" in texte or "perime" in texte, "un prix perime doit etre signale comme tel"
    assert "rupture" in texte
    assert "TotalEnergies" in texte


async def test_prix_station_par_adresse_rend_la_distance(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    """Si la station la plus proche est loin, l'adresse ne la designait pas."""
    fiche = {
        "id": 13008017,
        "enseigne": None,
        "adresse": "265 AVENUE DE MAZARGUES",
        "ville": "Marseille",
        "cp": "13008",
        "autoroute": False,
        "latitude": 43.263,
        "longitude": 5.393,
        "active": True,
        "premiere_vue": "2026-11-23T10:00:00Z",
        "derniere_vue": "2026-11-28T10:00:00Z",
        "services": [],
        "horaires": None,
        "prix": [
            {
                "carburant": "gazole",
                "prix_eur_l": 1.99,
                "maj": "2026-11-28T06:00:00Z",
                "fraicheur": "frais",
                "rupture": None,
            }
        ],
    }
    client = api(
        {
            "/v1/geocode": charges["geocode_precis"],
            "/v1/stations/proches": charges["proches"],
            "/v1/stations/13008017": fiche,
        }
    )
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "prix_station", {"station": "265 avenue de Mazargues, Marseille"}
        )
    assert not resultat.is_error, _texte(resultat)
    structure = _structure(resultat)
    assert structure["distance_de_l_adresse_km"] is not None
    assert "la plus proche de l'adresse" in _texte(resultat)


# ------------------------------------------------------------------ tendance_prix
async def test_la_tendance_dit_le_sens_et_l_ampleur(api: Fabrique, ouvrir: Session) -> None:
    serie = {
        "carburant": "gazole",
        "dimension": "france",
        "valeur": "",
        "jours": 30,
        "points": [
            {
                "jour": "2026-10-30",
                "stations": 9300,
                "exclus": 70,
                "prix_min_eur_l": 1.80,
                "prix_median_eur_l": 2.15,
                "prix_moyen_eur_l": 2.16,
                "prix_max_eur_l": 2.50,
            },
            {
                "jour": "2026-11-28",
                "stations": 9379,
                "exclus": 72,
                "prix_min_eur_l": 1.83,
                "prix_median_eur_l": 2.09,
                "prix_moyen_eur_l": 2.11,
                "prix_max_eur_l": 2.46,
            },
        ],
    }
    client = api({"/v1/tendances": serie})
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "tendance_prix", {"zone": "France", "carburant": "diesel", "periode": "ce mois-ci"}
        )
    assert not resultat.is_error, _texte(resultat)
    structure = _structure(resultat)
    assert structure["jours"] == 30, "« ce mois-ci » doit valoir trente jours"
    assert structure["variation_eur_l"] == pytest.approx(-0.06)
    assert structure["prix_debut_eur_l"] == pytest.approx(2.15)
    texte = _texte(resultat)
    assert "baisse" in texte
    assert "6" in texte, "l'ampleur en centimes doit figurer"


async def test_la_tendance_avertit_quand_l_historique_ne_couvre_pas_la_periode(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    client = api({"/v1/tendances": charges["tendances"]})
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "tendance_prix", {"zone": "France", "carburant": "gazole", "periode": "2 ans"}
        )
    assert not resultat.is_error, _texte(resultat)
    assert "depasse l'historique disponible" in _texte(resultat)


async def test_une_periode_incomprise_dit_comment_l_ecrire(api: Fabrique, ouvrir: Session) -> None:
    async with ouvrir(api({})) as cliente:
        resultat = await cliente.call_tool(
            "tendance_prix", {"zone": "France", "carburant": "gazole", "periode": "depuis Noel"}
        )
    assert resultat.is_error
    assert "ce mois-ci" in _texte(resultat), "l'erreur doit montrer un exemple valide"


# ------------------------------------------------------- empreinte et comparaison
async def test_l_empreinte_sort_avec_sa_source_complete(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    """Un facteur d'emission sans sa source ne vaut rien, et il se propagera."""
    client = api({"/v1/empreinte": charges["empreinte_gazole"]})
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "empreinte_carbone_plein", {"carburant": "gazole", "litres": 40}
        )
    assert not resultat.is_error, _texte(resultat)
    structure = _structure(resultat)
    assert structure["co2_kg"] == pytest.approx(124.0)
    source = structure["source"]
    for champ in ("libelle_ademe", "version_base", "url", "periode_validite"):
        assert source.get(champ), f"la source doit porter {champ}"
    texte = _texte(resultat)
    assert "ADEME" in texte
    assert "Gazole routier" in texte
    assert "kg" in texte and "CO2e" in texte


async def test_l_empreinte_refuse_plutot_que_d_inventer(api: Fabrique, ouvrir: Session) -> None:
    """Quand aucun facteur n'est charge, l'API repond 503 : on relaie le refus."""

    def repondre(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "type": "about:blank",
                "title": "Facteur d'emission indisponible",
                "status": 503,
                "detail": "Aucun facteur d'emission n'est charge pour ce carburant.",
            },
            headers={"content-type": "application/problem+json"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(repondre), base_url="https://api.test/v1"
    )
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool("empreinte_carbone_plein", {"carburant": "gazole"})
    assert resultat.is_error
    message = _texte(resultat)
    assert "Aucun facteur" in message
    assert "estimation" in message, "le refus doit interdire explicitement d'estimer"


async def test_la_comparaison_relaie_son_avertissement(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    """« L'E85 est le moins cher » est vrai au litre et faux a l'usage."""
    client = api(
        {
            "/v1/empreinte/comparaison": charges["comparaison"],
            "/v1/geocode": charges["geocode_precis"],
            "/v1/stations/proches": charges["proches"],
        }
    )
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool(
            "comparer_carburants", {"lieu": "40 avenue du Prado, 13006 Marseille"}
        )
    assert not resultat.is_error, _texte(resultat)
    structure = _structure(resultat)
    assert len(structure["carburants"]) == 6, "les six carburants, meme absents sur place"
    assert structure["avertissement"], "la comparaison doit dire ce qu'elle ne dit pas"
    texte = _texte(resultat)
    assert "meme distance" in texte or "même distance" in texte

    manquants = [
        entree for entree in structure["carburants"] if entree.get("indisponible_sur_place")
    ]
    assert manquants, "le jeu d'essai ne contient que du gazole : les autres manquent sur place"


async def test_la_comparaison_sans_lieu_ne_parle_que_de_co2(
    api: Fabrique, ouvrir: Session, charges: Charges
) -> None:
    client = api({"/v1/empreinte/comparaison": charges["comparaison"]})
    async with ouvrir(client) as cliente:
        resultat = await cliente.call_tool("comparer_carburants", {})
    assert not resultat.is_error, _texte(resultat)
    structure = _structure(resultat)
    assert structure["lieu"] is None
    assert all(entree.get("prix_le_moins_cher_eur_l") is None for entree in structure["carburants"])
    assert "CO2 seulement" in _texte(resultat)
