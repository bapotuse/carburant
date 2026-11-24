"""La regle d'ambiguite du geocodage.

`analyser` est une fonction pure : elle se teste sans reseau, avec les reponses
reellement observees de la Geoplateforme. Le test marque `reseau`, lui, interroge
vraiment l'IGN et verifie que les quatre verdicts de la reconnaissance tiennent
toujours.
"""

from __future__ import annotations

from typing import Any

import pytest
from carburant_api.routes.geocode import ECART_MINIMAL, SEUIL_SCORE, analyser


def trait(libelle: str, score: float, type_: str = "street") -> dict[str, Any]:
    """Un trait GeoJSON tel que la Geoplateforme le renvoie."""
    return {
        "properties": {
            "label": libelle,
            "score": score,
            "type": type_,
            "city": "Marseille",
            "postcode": "13008",
        },
        "geometry": {"type": "Point", "coordinates": [5.386189, 43.272573]},
    }


# Les quatre cas mesures le 23/11/2026, scores reels.


def test_adresse_complete_repond_directement() -> None:
    """« 40 avenue du Prado, 13006 Marseille » : 0,972, puis 0,455."""
    resultat = analyser(
        "40 avenue du Prado, 13006 Marseille",
        [
            trait("40 Avenue du prado 13006 Marseille", 0.972, "housenumber"),
            trait("Tunnel prado carenage 13006 Marseille", 0.455, "locality"),
        ],
    )
    assert resultat.ambigu is False
    assert resultat.raison is None
    assert resultat.candidats[0].type == "housenumber"


def test_code_postal_repond_directement() -> None:
    """« 13008 » : 0,865 pour la commune, 0,708 pour la suivante."""
    resultat = analyser(
        "13008",
        [
            trait("Marseille 8e Arrondissement", 0.865, "municipality"),
            trait("Avenue du prado 13008 Marseille", 0.708),
        ],
    )
    assert resultat.ambigu is False


def test_un_lieu_connu_mais_vague_demande_a_preciser() -> None:
    """« le Prado, Marseille » : le meilleur candidat ne marque que 0,608."""
    resultat = analyser(
        "le Prado, Marseille",
        [
            trait("Allee prado bleu 13008 Marseille", 0.608),
            trait("Avenue du prado 13008 Marseille", 0.595),
        ],
    )
    assert resultat.ambigu is True
    assert resultat.raison is not None
    assert "0,608" in resultat.raison


def test_prado_marseille_demande_a_preciser() -> None:
    """« Prado Marseille » : 0,708 et 0,699.

    L'avenue du Prado existe en 13006 et en 13008, a 1,2 km l'une de l'autre, et les
    deux ne sont separees que de 0,009 point. Les deux conditions d'ambiguite sont
    reunies ; c'est celle du score trop faible qui est rapportee, parce que 0,708 est
    deja sous le seuil de 0,80.
    """
    resultat = analyser(
        "Prado Marseille",
        [
            trait("Avenue du prado 13008 Marseille", 0.708),
            trait("Avenue du prado 13006 Marseille", 0.699),
        ],
    )
    assert resultat.ambigu is True
    assert resultat.raison is not None
    assert "0,708" in resultat.raison


def test_deux_bons_candidats_trop_proches_demandent_a_preciser() -> None:
    """La regle de l'ecart, isolee : deux candidats surs mais indiscernables.

    C'est le cas qu'on ne veut surtout pas trancher au hasard -- deux adresses
    plausibles a plusieurs kilometres l'une de l'autre.
    """
    resultat = analyser(
        "rue de la Republique",
        [
            trait("Rue de la republique 13001 Marseille", 0.912, "street"),
            trait("Rue de la republique 13002 Marseille", 0.908, "street"),
        ],
    )
    assert resultat.ambigu is True
    assert resultat.raison is not None
    assert "0,004" in resultat.raison


# Bornes de la regle.


def test_la_borne_du_score_est_inclusive() -> None:
    assert analyser("x", [trait("a", SEUIL_SCORE)]).ambigu is False
    assert analyser("x", [trait("a", SEUIL_SCORE - 0.001)]).ambigu is True


def test_la_borne_de_l_ecart_est_inclusive() -> None:
    bon = analyser("x", [trait("a", 0.95), trait("b", 0.95 - ECART_MINIMAL)])
    limite = analyser("x", [trait("a", 0.95), trait("b", 0.95 - ECART_MINIMAL + 0.001)])
    assert bon.ambigu is False
    assert limite.ambigu is True


def test_un_candidat_unique_et_sur_n_est_pas_ambigu() -> None:
    assert analyser("x", [trait("a", 0.99, "housenumber")]).ambigu is False


def test_aucun_resultat_est_signale_comme_ambigu() -> None:
    resultat = analyser("zzz", [])
    assert resultat.ambigu is True
    assert resultat.raison == "aucun lieu trouve"
    assert resultat.candidats == []


# Filtrage.


def test_les_types_inutiles_sont_ecartes() -> None:
    """Le geocodeur renvoie des types qui ne sont pas des lieux ou l'on va."""
    resultat = analyser("x", [trait("Quelque chose", 0.9, "parcel")])
    assert resultat.candidats == []


def test_les_tunnels_passent_en_dernier() -> None:
    """Ils polluent les resultats marseillais sans jamais etre la bonne reponse."""
    resultat = analyser(
        "prado",
        [
            trait("Tunnel prado carenage 13006 Marseille", 0.98, "locality"),
            trait("Avenue du prado 13008 Marseille", 0.70),
        ],
    )
    assert resultat.candidats[0].libelle == "Avenue du prado 13008 Marseille"


def test_les_coordonnees_sont_lues_dans_le_bon_ordre() -> None:
    """GeoJSON donne [longitude, latitude], pas l'inverse. Les confondre mettrait
    Marseille en Somalie."""
    resultat = analyser("x", [trait("a", 0.99, "housenumber")])
    assert resultat.candidats[0].longitude == pytest.approx(5.386189)
    assert resultat.candidats[0].latitude == pytest.approx(43.272573)


# Contre le vrai service.


@pytest.mark.reseau
@pytest.mark.parametrize(
    ("requete", "ambigu_attendu"),
    [
        ("40 avenue du Prado, 13006 Marseille", False),
        ("13008", False),
        ("le Prado, Marseille", True),
        ("Prado Marseille", True),
    ],
)
def test_les_verdicts_tiennent_contre_le_vrai_geocodeur(requete: str, ambigu_attendu: bool) -> None:
    """Interroge vraiment la Geoplateforme.

    Si l'IGN modifie son classement, ce test le dira avant que le site ne se mette a
    deviner a la place de l'utilisateur.
    """
    import httpx
    from carburant_api.routes.geocode import URL_GEOPLATEFORME

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        reponse = client.get(
            URL_GEOPLATEFORME, params={"q": requete, "limit": 5, "index": "address"}
        )
        reponse.raise_for_status()

    resultat = analyser(requete, reponse.json().get("features") or [])
    assert resultat.ambigu is ambigu_attendu, (
        f"{requete!r} : scores {[c.score for c in resultat.candidats]} -> {resultat.raison}"
    )
