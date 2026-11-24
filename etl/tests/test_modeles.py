"""Validation et aplatissement : chaque piege de la reconnaissance a son test."""

from __future__ import annotations

from typing import Any

import pytest
from carburant_etl.modeles import aplatir, normaliser_horaires


def station(**surcharges: Any) -> dict[str, Any]:
    """Une ligne de flux minimale et valide, surchargeable champ par champ."""
    base: dict[str, Any] = {
        "id": 56580001,
        "geom": {"lat": 48.061, "lon": -2.69},
        # Presents dans le flux mais jamais utilises : degres x 100 000.
        "latitude": "4806100",
        "longitude": "-269000",
        "cp": "56580",
        "pop": "R",
        "adresse": "16 rue chateaubriand",
        "ville": "Brehan",
        "departement": "Morbihan",
        "code_departement": "56",
        "region": "Bretagne",
        "code_region": "53",
        "services_service": ["Piste poids lourds", "Automate CB 24/24"],
        "gazole_prix": 2.109,
        "gazole_maj": "2026-11-23T17:00:00+00:00",
    }
    base.update(surcharges)
    return base


# ---------------------------------------------------------------- cas nominal


def test_aplatissement_nominal() -> None:
    resultat = aplatir([station()])

    assert resultat.lignes_lues == 1
    assert resultat.stations_rejetees == 0
    assert resultat.rejets.total == 0

    s = resultat.stations[0]
    assert s.station_id == 56580001
    assert s.ville == "Brehan"
    assert s.code_departement == "56"
    assert s.services == ["Piste poids lourds", "Automate CB 24/24"]

    assert len(resultat.prix) == 1
    p = resultat.prix[0]
    assert p.carburant == "gazole"
    assert p.prix == 2.109
    # 17 h 00 a Paris en novembre, c'est 16 h 00 UTC. Le suffixe +00:00 du flux ment.
    assert p.maj == "2026-11-23T16:00:00+00:00"


def test_les_coordonnees_viennent_de_geom_pas_des_champs_texte() -> None:
    """`latitude` et `longitude` sont en degres x 100 000 : les lire serait une faute."""
    s = aplatir([station()]).stations[0]
    assert s.latitude == 48.061
    assert s.longitude == -2.69


def test_une_station_sans_prix_ni_rupture_ne_produit_aucune_ligne_de_prix() -> None:
    """1,8 % des stations du flux n'ont aucun prix : elles existent quand meme."""
    brut = station()
    del brut["gazole_prix"], brut["gazole_maj"]
    resultat = aplatir([brut])
    assert len(resultat.stations) == 1
    assert resultat.prix == []


def test_les_six_carburants_sont_aplatis_en_six_lignes() -> None:
    brut = station(
        sp95_prix=1.999,
        sp95_maj="2026-11-23T10:00:00+00:00",
        e10_prix=1.949,
        e10_maj="2026-11-23T10:00:00+00:00",
        sp98_prix=2.038,
        sp98_maj="2026-11-23T10:00:00+00:00",
        e85_prix=0.869,
        e85_maj="2026-11-23T10:00:00+00:00",
        gplc_prix=1.075,
        gplc_maj="2026-11-23T10:00:00+00:00",
    )
    resultat = aplatir([brut])
    assert {p.carburant for p in resultat.prix} == {"gazole", "sp95", "e10", "sp98", "e85", "gplc"}


# ---------------------------------------------------------------- rejets


def test_une_station_hors_emprise_est_rejetee_et_comptee() -> None:
    """Les archives contiennent des latitudes a 62 degres. Le flux, non -- mais on verifie."""
    resultat = aplatir([station(geom={"lat": 62.6, "lon": 5.0})])
    assert resultat.stations == []
    assert resultat.stations_rejetees == 1
    champs = {champ for champ, _, _, _ in resultat.rejets.lignes()}
    assert "geom.lat" in champs


def test_une_station_en_outre_mer_est_rejetee() -> None:
    """La Reunion : -20,95 / 55,29. Absente du flux, presente dans les archives."""
    resultat = aplatir([station(geom={"lat": -20.95, "lon": 55.29})])
    assert resultat.stations == []


def test_un_identifiant_absent_rejette_la_station() -> None:
    brut = station()
    del brut["id"]
    resultat = aplatir([brut])
    assert resultat.stations == []
    assert any(champ == "id" for champ, _, _, _ in resultat.rejets.lignes())


def test_un_pop_inattendu_est_rejete() -> None:
    """Le flux ne connait que R et A."""
    resultat = aplatir([station(pop="Z")])
    assert resultat.stations == []
    assert any(champ == "pop" for champ, _, _, _ in resultat.rejets.lignes())


def test_une_station_en_double_dans_l_export_est_comptee_une_fois() -> None:
    resultat = aplatir([station(), station()])
    assert len(resultat.stations) == 1
    motifs = {motif for champ, motif, _, _ in resultat.rejets.lignes() if champ == "id"}
    assert "station en double dans l'export" in motifs


def test_une_entree_qui_n_est_pas_un_objet_est_comptee() -> None:
    resultat = aplatir(["pas un objet", 42, None])
    assert resultat.stations == []
    assert resultat.rejets.comptes[("ligne", "entree non objet")] == 3


def test_une_station_cassee_ne_prive_pas_les_autres() -> None:
    """Une seule ligne mal formee ne doit pas faire perdre les 9 825 autres."""
    resultat = aplatir([station(geom="n'importe quoi"), station(id=12345678)])
    assert len(resultat.stations) == 1
    assert resultat.stations[0].station_id == 12345678


# ---------------------------------------------------------------- prix


@pytest.mark.parametrize(
    ("carburant", "valeur", "garde"),
    [
        ("gazole", 2.109, True),
        ("gazole", 2.900, True),
        ("e85", 0.869, True),
        # Les 4 vraies erreurs de saisie du 23/11 : des prix de SP95 dans la case E85.
        ("e85", 1.990, False),
        ("e85", 2.249, False),
        ("gazole", 0.019, False),
        ("gazole", 19.9, False),
    ],
)
def test_les_bornes_absolues_rejettent_et_comptent(
    carburant: str, valeur: float, garde: bool
) -> None:
    brut = station()
    del brut["gazole_prix"], brut["gazole_maj"]
    brut[f"{carburant}_prix"] = valeur
    brut[f"{carburant}_maj"] = "2026-11-23T10:00:00+00:00"

    resultat = aplatir([brut])

    if garde:
        assert [p.prix for p in resultat.prix] == [valeur]
    else:
        assert resultat.prix == []
        motifs = {motif for _, motif, _, _ in resultat.rejets.lignes()}
        assert "hors bornes absolues" in motifs


def test_un_prix_sans_date_est_rejete() -> None:
    """La spec interdit d'afficher un prix nu : un prix sans date est inexploitable."""
    brut = station()
    del brut["gazole_maj"]
    resultat = aplatir([brut])
    assert resultat.prix == []
    motifs = {motif for _, motif, _, _ in resultat.rejets.lignes()}
    assert "prix sans date de mise a jour" in motifs


def test_un_prix_non_numerique_est_rejete() -> None:
    resultat = aplatir([station(gazole_prix="deux euros")])
    assert resultat.prix == []
    assert any(champ == "gazole_prix" for champ, _, _, _ in resultat.rejets.lignes())


def test_un_horodatage_illisible_est_compte() -> None:
    resultat = aplatir([station(gazole_maj="pas une date")])
    assert resultat.prix == []
    motifs = {motif for _, motif, _, _ in resultat.rejets.lignes()}
    assert "horodatage illisible" in motifs


# ---------------------------------------------------------------- ruptures


def test_une_rupture_sans_prix_produit_quand_meme_une_ligne() -> None:
    """Une rupture definitive dit « cette station ne vend pas ce carburant ».
    C'est une information, pas une absence."""
    brut = station(
        gplc_rupture_type="definitive",
        gplc_rupture_debut="2017-10-06T16:05:31+00:00",
    )
    resultat = aplatir([brut])
    gplc = next(p for p in resultat.prix if p.carburant == "gplc")
    assert gplc.prix is None
    assert gplc.rupture_type == "definitive"
    assert gplc.rupture_debut == "2017-10-06T14:05:31+00:00"  # octobre : UTC+2


def test_un_type_de_rupture_inattendu_est_rejete() -> None:
    resultat = aplatir([station(sp95_rupture_type="peut-etre")])
    assert all(p.rupture_type != "peut-etre" for p in resultat.prix)
    motifs = {motif for _, motif, _, _ in resultat.rejets.lignes()}
    assert "type inattendu" in motifs


# ---------------------------------------------------------------- horaires


def test_horaires_avec_une_seule_plage() -> None:
    normalise = normaliser_horaires(
        {
            "@automate-24-24": "1",
            "jour": [
                {
                    "@id": "1",
                    "@nom": "Lundi",
                    "@ferme": "",
                    "horaire": {"@ouverture": "08.00", "@fermeture": "12.00"},
                }
            ],
        }
    )
    assert normalise is not None
    assert normalise["automate_24_24"] is True
    assert normalise["jours"][0] == {
        "jour": 1,
        "nom": "Lundi",
        "ferme": False,
        "plages": [["08:00", "12:00"]],
    }


def test_horaires_avec_deux_plages_dans_la_journee() -> None:
    """`horaire` est tantot un objet, tantot une liste : les deux existent dans le flux."""
    normalise = normaliser_horaires(
        {
            "@automate-24-24": "",
            "jour": [
                {
                    "@id": "3",
                    "@nom": "Mercredi",
                    "@ferme": "",
                    "horaire": [
                        {"@ouverture": "08.00", "@fermeture": "12.00"},
                        {"@ouverture": "14.00", "@fermeture": "19.00"},
                    ],
                }
            ],
        }
    )
    assert normalise is not None
    assert normalise["automate_24_24"] is False
    assert normalise["jours"][0]["plages"] == [["08:00", "12:00"], ["14:00", "19:00"]]


def test_une_journee_fermee_perd_ses_plages() -> None:
    """Vu en vrai : `@ferme="1"` avec une plage 01.00 -> 01.00. Le ferme l'emporte."""
    normalise = normaliser_horaires(
        {
            "@automate-24-24": "1",
            "jour": [
                {
                    "@id": "1",
                    "@nom": "Lundi",
                    "@ferme": "1",
                    "horaire": {"@ouverture": "01.00", "@fermeture": "01.00"},
                }
            ],
        }
    )
    assert normalise is not None
    assert normalise["jours"][0]["ferme"] is True
    assert normalise["jours"][0]["plages"] == []


def test_une_journee_sans_horaire_reste_ouverte_sans_plage() -> None:
    normalise = normaliser_horaires(
        {"@automate-24-24": "", "jour": [{"@id": "2", "@nom": "Mardi", "@ferme": ""}]}
    )
    assert normalise is not None
    assert normalise["jours"][0] == {
        "jour": 2,
        "nom": "Mardi",
        "ferme": False,
        "plages": [],
    }


def test_les_horaires_acceptent_une_chaine_json() -> None:
    """Le csv donne le champ sous forme de chaine ; le json sous forme d'objet."""
    brut = '{"@automate-24-24": "1", "jour": [{"@id": "7", "@nom": "Dimanche", "@ferme": "1"}]}'
    normalise = normaliser_horaires(brut)
    assert normalise is not None
    assert normalise["jours"][0]["ferme"] is True


@pytest.mark.parametrize("valeur", [None, "", "pas du json", 42, [], {"jour": "n'importe"}])
def test_des_horaires_illisibles_ne_font_pas_perdre_la_station(valeur: object) -> None:
    """13,1 % des stations n'ont pas d'horaires : ce n'est pas une raison de les perdre."""
    resultat = aplatir([station(horaires=valeur)])
    assert len(resultat.stations) == 1
    assert len(resultat.prix) == 1


def test_une_heure_invalide_est_ignoree_sans_casser_la_journee() -> None:
    normalise = normaliser_horaires(
        {
            "@automate-24-24": "",
            "jour": [
                {
                    "@id": "1",
                    "@nom": "Lundi",
                    "@ferme": "",
                    "horaire": [
                        {"@ouverture": "99.99", "@fermeture": "12.00"},
                        {"@ouverture": "08.00", "@fermeture": "12.00"},
                    ],
                }
            ],
        }
    )
    assert normalise is not None
    assert normalise["jours"][0]["plages"] == [["08:00", "12:00"]]


# ---------------------------------------------------------------- rapport de rejets


def test_le_rapport_de_rejets_compte_et_donne_un_exemple() -> None:
    resultat = aplatir(
        [
            station(id=1, geom={"lat": 62.6, "lon": 5.0}),
            station(id=2, geom={"lat": 63.0, "lon": 5.0}),
            station(id=3, pop="Z"),
        ]
    )
    lignes = {
        (champ, motif): (nombre, exemple)
        for champ, motif, nombre, exemple in resultat.rejets.lignes()
    }
    latitudes = [v for (champ, _), v in lignes.items() if champ == "geom.lat"]
    assert latitudes and latitudes[0][0] == 2
    assert latitudes[0][1] is not None, "un exemple doit etre garde pour diagnostiquer"
    assert resultat.rejets.total >= 3


@pytest.mark.reseau
def test_aplatissement_de_l_export_reel(tmp_path: Any) -> None:
    """Aplatit le vrai export et compare aux chiffres de la reconnaissance.

    C'est le test qui attrape une derive de la source : si un champ disparait ou si
    les volumes s'effondrent, il echoue avant que la base ne se remplisse de vide.
    """
    import gzip
    import json as _json

    from carburant_etl.sources.flux_v2 import telecharger

    collecte = telecharger(tmp_path, user_agent="carburant-test/0.1")
    assert collecte.chemin is not None
    with gzip.open(collecte.chemin, "rb") as flux:
        export = _json.load(flux)

    resultat = aplatir(export)

    # Mesure du 23/11/2026 : 9 826 stations. On tolere large, mais pas un effondrement.
    assert 8_000 <= len(resultat.stations) <= 12_000, len(resultat.stations)
    # 32 867 couples station x carburant avec un prix, plus les ruptures.
    assert len(resultat.prix) >= 25_000, len(resultat.prix)

    # Les six carburants doivent tous etre representes.
    carburants = {p.carburant for p in resultat.prix}
    assert carburants == {"gazole", "sp95", "e10", "sp98", "e85", "gplc"}

    # Le gazole est quasi universel : 96,7 % des stations en ont un prix.
    avec_gazole = sum(1 for p in resultat.prix if p.carburant == "gazole" and p.prix)
    assert avec_gazole / len(resultat.stations) > 0.85

    # Le departement vient du flux : il doit etre renseigne presque partout.
    sans_departement = sum(1 for s in resultat.stations if not s.code_departement)
    assert sans_departement <= 20, sans_departement

    # Corse presente, outre-mer absent : c'est ce que dit la reconnaissance.
    codes = {s.code_departement for s in resultat.stations if s.code_departement}
    assert {"2A", "2B"} <= codes
    assert not any(c.startswith(("97", "98")) for c in codes)

    # Les rejets doivent rester marginaux. Au-dela, la source a change.
    assert resultat.rejets.total < len(resultat.stations) * 0.02, resultat.rejets.lignes()
