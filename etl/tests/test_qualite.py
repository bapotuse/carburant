"""Controles qualite et agregats, contre une vraie base PostGIS.

Ces regles sont ecrites en SQL : les tester contre une base simulee ne dirait rien
de `percentile_cont`, des partitions ni de `ST_Intersects`. Chaque test construit la
situation qu'il veut voir signalee, puis verifie que le controle la signale -- et,
tout aussi important, que les autres controles restent au vert.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from zoneinfo import ZoneInfo

import psycopg
import pytest
from carburant_etl.chargement import agregats
from carburant_etl.chargement.migrations import appliquer
from carburant_etl.chargement.staging import ouvrir
from carburant_etl.modeles import LignePrix, LigneStation
from carburant_etl.qualite import controles
from carburant_etl.transformation import aberrants

from .test_marts import charger_tout, nombre, prix, station

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")

PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture
def base() -> Iterator[str]:
    assert URL
    nom = f"carburant_qualite_{uuid.uuid4().hex[:12]}"
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


def verdicts_par_nom(
    connexion: psycopg.Connection[tuple[object, ...]],
) -> dict[str, controles.Verdict]:
    return {v.nom: v for v in controles.executer(connexion)}


def un_departement(
    *, combien: int, prix_eur: float, instant: dt.datetime, premier_id: int = 13000001
) -> tuple[list[LigneStation], list[LignePrix]]:
    """`combien` stations du meme departement affichant toutes le meme prix.

    C'est la situation qui a piege la regle initiale : quand tout le monde affiche le
    meme prix, la MAD tombe a zero et le moindre ecart devient enorme en nombre de
    MAD. Le plancher de 0,05 EUR existe pour cela.
    """
    stations = [
        station(
            premier_id + n,
            cp="13008",
            ville="Marseille",
            departement="Bouches-du-Rhone",
            code_departement="13",
            longitude=5.39 + n * 0.001,
            latitude=43.27,
        )
        for n in range(combien)
    ]
    lignes = [
        prix(
            instant.strftime("%Y-%m-%dT%H:%M:%S"),
            valeur=prix_eur,
            identifiant=premier_id + n,
        )
        for n in range(combien)
    ]
    return stations, lignes


# --------------------------------------------------------------------- la regle
@sans_base
def test_les_constantes_sql_et_python_sont_les_memes(base: str) -> None:
    """Une regle, deux implementations : elles doivent partager leurs seuils.

    La regle vit en SQL (lue par l'API et les agregats) et en Python (lue par l'ETL).
    Si l'une derive, le site signalerait des prix que l'ETL juge normaux.
    """
    connexion = ouvrir(base)
    try:
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT marts.plancher_mad(), marts.facteur_mad(), marts.min_stations_departement()"
            )
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert ligne is not None
    plancher, facteur, minimum = ligne
    assert nombre(plancher) == aberrants.PLANCHER_MAD
    assert nombre(facteur) == aberrants.FACTEUR_MAD
    assert nombre(minimum) == aberrants.MIN_STATIONS_DEPARTEMENT


@sans_base
@pytest.mark.parametrize(
    ("ecart", "attendu"),
    [
        (0.20, False),  # 4 MAD plancherees : sous le seuil de 5
        (0.26, True),  # 5,2 MAD plancherees : au-dessus
    ],
)
def test_sql_et_python_jugent_pareil_aux_bornes(base: str, ecart: float, attendu: bool) -> None:
    """Aux abords du seuil, les deux implementations doivent dire la meme chose."""
    mediane, mad, stations = 1.800, 0.0, 10
    connexion = ouvrir(base)
    try:
        with connexion.cursor() as curseur:
            # Les casts sont necessaires : la fonction prend des `numeric`, et
            # PostgreSQL ne convertit pas implicitement un `double precision` en
            # `numeric`. En production les arguments viennent de colonnes numeric.
            curseur.execute(
                "SELECT marts.est_suspect(%s::numeric, %s::numeric, %s::numeric, %s::integer)",
                (mediane + ecart, mediane, mad, stations),
            )
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert ligne is not None
    cote_sql = bool(ligne[0])
    cote_python = aberrants.est_suspect(mediane + ecart, mediane, mad, nombre_de_stations=stations)
    assert cote_sql == cote_python == attendu


@sans_base
def test_un_departement_trop_petit_ne_juge_personne(base: str) -> None:
    """Moins de cinq stations : on ne juge pas un prix sur trois voisins.

    Le seuil est bien **strictement** moins de cinq : a cinq stations la regle
    s applique. On en met donc quatre en tout, prix delirant compris.
    """
    instant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    stations, lignes = un_departement(combien=3, prix_eur=1.800, instant=instant)
    stations_hors, lignes_hors = un_departement(
        combien=1, prix_eur=3.400, instant=instant, premier_id=13009001
    )
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations + stations_hors, lignes + lignes_hors)
        agregats.rafraichir_reference(connexion)
        with connexion.cursor() as curseur:
            curseur.execute("SELECT count(*) FROM marts.prix_courant_qualifie WHERE suspect")
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert ligne is not None
    assert ligne[0] == 0, "un departement de 4 stations ne devrait juger personne"


@sans_base
def test_le_plancher_de_mad_evite_de_signaler_tout_le_monde(base: str) -> None:
    """Sans plancher, un departement ou tout le monde affiche le meme prix explose.

    Neuf stations a 1,800 EUR et une a 1,810 : la MAD vaut 0, donc sans plancher
    l'ecart de la dixieme serait infini en nombre de MAD. Avec le plancher, 0,01 EUR
    reste un ecart de 0,2 MAD : personne n'est signale.
    """
    instant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    stations, lignes = un_departement(combien=9, prix_eur=1.800, instant=instant)
    station_voisine, prix_voisin = un_departement(
        combien=1, prix_eur=1.810, instant=instant, premier_id=13009001
    )
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations + station_voisine, lignes + prix_voisin)
        agregats.rafraichir_reference(connexion)
        with connexion.cursor() as curseur:
            curseur.execute("SELECT mad FROM marts.reference_departementale")
            mad = curseur.fetchone()
            curseur.execute("SELECT count(*) FROM marts.prix_courant_qualifie WHERE suspect")
            suspects = curseur.fetchone()
    finally:
        connexion.close()
    assert mad is not None and nombre(mad[0]) == 0.0, "la MAD devrait bien etre nulle ici"
    assert suspects is not None and suspects[0] == 0


@sans_base
def test_un_prix_vraiment_atypique_est_signale_sans_etre_rejete(base: str) -> None:
    """L'Ile-d'Yeu : un prix bien plus eleve, conserve et affiche, mais signale."""
    instant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    stations, lignes = un_departement(combien=9, prix_eur=1.800, instant=instant)
    ile, prix_ile = un_departement(combien=1, prix_eur=2.400, instant=instant, premier_id=13009001)
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations + ile, lignes + prix_ile)
        agregats.rafraichir_reference(connexion)
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT station_id, prix, suspect, round(ecart_mad, 1) "
                "FROM marts.prix_courant_qualifie WHERE suspect"
            )
            signales = curseur.fetchall()
            curseur.execute("SELECT count(*) FROM marts.fact_prix")
            total = curseur.fetchone()
    finally:
        connexion.close()
    assert len(signales) == 1, f"un seul prix devrait etre signale : {signales}"
    assert signales[0][0] == 13009001
    assert nombre(signales[0][1]) == 2.400
    assert total is not None and total[0] == 10, "le prix signale reste en base"


# --------------------------------------------------------------- les controles
@sans_base
def test_tous_les_controles_passent_sur_une_base_saine(base: str) -> None:
    instant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    stations, lignes = un_departement(combien=9, prix_eur=1.800, instant=instant)
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations, lignes)
        agregats.rafraichir(connexion, jours=1)
        verdicts = verdicts_par_nom(connexion)
    finally:
        connexion.close()
    en_echec = [nom for nom, v in verdicts.items() if not v.ok]
    assert en_echec == [], f"controles en echec sur une base saine : {en_echec}"
    assert controles.echecs_bloquants(list(verdicts.values())) == []


@sans_base
def test_une_station_hors_de_france_est_signalee(base: str) -> None:
    """Les archives annuelles contiennent des coordonnees aberrantes : ce controle
    existe pour que l'amorcage ne les laisse pas entrer en silence."""
    instant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    stations, lignes = un_departement(combien=5, prix_eur=1.800, instant=instant)
    # Latitude 62,6 : la valeur reellement observee dans l'archive 2025.
    stations[0] = station(
        13000001,
        cp="13008",
        ville="Marseille",
        code_departement="13",
        longitude=5.39,
        latitude=62.6,
    )
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations, lignes)
        agregats.rafraichir_reference(connexion)
        verdicts = verdicts_par_nom(connexion)
    finally:
        connexion.close()
    verdict = verdicts["coordonnees_dans_emprise"]
    assert not verdict.ok
    assert verdict.bloquant
    assert "1 station" in verdict.mesure


@sans_base
def test_une_date_dans_le_futur_est_signalee(base: str) -> None:
    """Le garde-fou du fuseau horaire.

    Les dates du flux sont en heure de Paris malgre un suffixe `+00:00` mensonger.
    Si la source passait un jour reellement en UTC, nos dates partiraient deux heures
    dans le futur en ete. C'est ce controle qui l'apprendrait.
    """
    instant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    futur = instant + dt.timedelta(hours=3)
    stations, lignes = un_departement(combien=5, prix_eur=1.800, instant=futur)
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations, lignes)
        agregats.rafraichir_reference(connexion)
        verdicts = verdicts_par_nom(connexion)
    finally:
        connexion.close()
    verdict = verdicts["aucune_date_future"]
    assert not verdict.ok
    assert verdict.bloquant
    assert "futur" in verdict.mesure


@sans_base
def test_le_resume_distingue_bloquants_et_alertes() -> None:
    verdicts = [
        controles.Verdict("a", "?", ok=True, mesure="", bloquant=True),
        controles.Verdict("b", "?", ok=False, mesure="", bloquant=False),
        controles.Verdict("c", "?", ok=False, mesure="", bloquant=True),
    ]
    assert controles.echecs_bloquants(verdicts) == [verdicts[2]]
    texte = controles.resume(verdicts)
    assert "2 en echec" in texte
    assert "1 bloquant" in texte


# ---------------------------------------------------------------- les agregats
def test_une_journee_finit_a_minuit_heure_de_paris() -> None:
    """Le 3 mars finit a minuit a Paris, pas a minuit UTC.

    Une station qui change son prix a 23 h 30 le 3 mars le change bien le 3 mars.
    """
    assert agregats.fin_du_jour(dt.date(2026, 3, 3)) == dt.datetime(2026, 3, 4, tzinfo=PARIS)


@pytest.mark.parametrize(
    ("jour", "decalage_heures"),
    [
        (dt.date(2026, 3, 28), 1),  # la veille du passage a l'heure d'ete
        (dt.date(2026, 3, 29), 2),  # le jour du passage : le lendemain est en UTC+2
        (dt.date(2026, 10, 24), 2),  # la veille du retour a l'heure d'hiver
        (dt.date(2026, 10, 25), 1),  # le jour du retour
    ],
)
def test_les_changements_d_heure_sont_pris_en_compte(jour: dt.date, decalage_heures: int) -> None:
    """Deux jours par an, une journee francaise ne dure pas 24 heures."""
    fin = agregats.fin_du_jour(jour)
    decalage = fin.utcoffset()
    assert decalage is not None
    assert decalage == dt.timedelta(hours=decalage_heures)


@sans_base
def test_les_agregats_ecartent_les_prix_atypiques_et_les_comptent(base: str) -> None:
    """Un agregat doit dire sur quoi il ne porte pas."""
    instant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    stations, lignes = un_departement(combien=9, prix_eur=1.800, instant=instant)
    ile, prix_ile = un_departement(combien=1, prix_eur=2.400, instant=instant, premier_id=13009001)
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations + ile, lignes + prix_ile)
        agregats.rafraichir(connexion, jours=1)
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT stations, exclus, prix_min, prix_median, prix_max "
                "FROM marts.agregat_prix_jour "
                "WHERE dimension = 'france' AND carburant = 'gazole'"
            )
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert ligne is not None, "un agregat national devrait exister"
    stations_comptees, exclus, minimum, mediane, maximum = ligne
    assert stations_comptees == 9
    assert exclus == 1, "le prix atypique doit etre compte comme exclu"
    assert nombre(maximum) == 1.800, "le prix a 2,400 ne doit pas tirer le maximum"
    assert nombre(minimum) == nombre(mediane) == 1.800


@sans_base
def test_un_agregat_est_recalculable_sans_doublon(base: str) -> None:
    """Rejouer `etl refresh` ne doit pas empiler les lignes."""
    instant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    stations, lignes = un_departement(combien=6, prix_eur=1.750, instant=instant)
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations, lignes)
        premier = agregats.rafraichir(connexion, jours=1)
        second = agregats.rafraichir(connexion, jours=1)
        with connexion.cursor() as curseur:
            curseur.execute("SELECT count(*) FROM marts.agregat_prix_jour")
            total = curseur.fetchone()
    finally:
        connexion.close()
    assert premier.lignes_agregat == second.lignes_agregat
    assert total is not None
    assert total[0] == premier.lignes_agregat, "le second passage a cree des doublons"


@sans_base
def test_un_prix_perime_ne_compte_pas_dans_l_agregat(base: str) -> None:
    """Un prix de plus de 30 jours ne temoigne plus du prix pratique."""
    instant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    vieux = instant - dt.timedelta(days=45)
    stations, lignes = un_departement(combien=5, prix_eur=1.800, instant=instant)
    perimees, prix_perimes = un_departement(
        combien=3, prix_eur=1.200, instant=vieux, premier_id=13009001
    )
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations + perimees, lignes + prix_perimes)
        agregats.rafraichir(connexion, jours=1)
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT stations, prix_min FROM marts.agregat_prix_jour "
                "WHERE dimension = 'france' AND carburant = 'gazole'"
            )
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert ligne is not None
    assert ligne[0] == 5, "seules les stations au prix non perime comptent"
    assert nombre(ligne[1]) == 1.800, "le prix perime a 1,200 ne doit pas tirer le minimum"


@sans_base
def test_le_calcul_en_masse_deplie_la_validite_de_chaque_prix(base: str) -> None:
    """Un changement de prix vaut jusqu'au suivant, et au plus trente jours.

    Calculer jour par jour conviendrait pour un ou deux jours ; sur dix-neuf ans ce
    serait 7 000 requetes. La version en masse deplie chaque changement sur sa duree
    de validite en une passe.
    """
    base_jour = dt.date(2026, 3, 2)
    premier = dt.datetime(2026, 3, 2, 10, tzinfo=PARIS)
    second = dt.datetime(2026, 3, 5, 10, tzinfo=PARIS)
    stations, lignes = un_departement(combien=6, prix_eur=1.700, instant=premier)
    _, lignes_apres = un_departement(combien=6, prix_eur=1.900, instant=second)

    connexion = ouvrir(base)
    try:
        charger_tout(connexion, premier, stations, lignes)
        charger_tout(connexion, second, stations, lignes_apres, sha="b" * 64)
        agregats.calculer_periode(connexion, base_jour, dt.date(2026, 3, 8))
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT jour, prix_median FROM marts.agregat_prix_jour "
                "WHERE dimension = 'france' AND carburant = 'gazole' ORDER BY jour"
            )
            serie = [(j, nombre(p)) for j, p in curseur.fetchall()]
    finally:
        connexion.close()

    par_jour = dict(serie)
    # Du 2 au 4 mars, le premier prix est en vigueur ; a partir du 5, le second.
    assert par_jour[dt.date(2026, 3, 3)] == 1.700
    assert par_jour[dt.date(2026, 3, 4)] == 1.700
    assert par_jour[dt.date(2026, 3, 5)] == 1.900
    assert par_jour[dt.date(2026, 3, 8)] == 1.900, "le dernier prix reste en vigueur"


@sans_base
def test_le_calcul_en_masse_est_rejouable(base: str) -> None:
    instant = dt.datetime(2026, 3, 2, 10, tzinfo=PARIS)
    stations, lignes = un_departement(combien=6, prix_eur=1.700, instant=instant)
    connexion = ouvrir(base)
    try:
        charger_tout(connexion, instant, stations, lignes)
        premier = agregats.calculer_periode(connexion, dt.date(2026, 3, 2), dt.date(2026, 3, 4))
        second = agregats.calculer_periode(connexion, dt.date(2026, 3, 2), dt.date(2026, 3, 4))
        with connexion.cursor() as curseur:
            curseur.execute("SELECT count(*) FROM marts.agregat_prix_jour")
            total = curseur.fetchone()
    finally:
        connexion.close()
    assert premier == second
    assert total is not None and total[0] == premier


@sans_base
def test_une_periode_a_l_envers_est_refusee(base: str) -> None:
    """Une periode inversee est une erreur d appel, pas une periode vide."""
    connexion = ouvrir(base)
    try:
        with pytest.raises(ValueError, match="envers"):
            agregats.calculer_periode(connexion, dt.date(2026, 3, 5), dt.date(2026, 3, 1))
    finally:
        connexion.close()


@sans_base
def test_les_deux_chemins_donnent_le_meme_resultat(base: str) -> None:
    """Le calcul jour par jour et le calcul en masse doivent s accorder.

    C'est le test qui manquait. L'audit du 26/11/2026 a trouve que le chemin en masse
    accordait trente et un jours de validite a un prix la ou le chemin jour par jour
    en accordait trente : 23 prix de gazole d'ecart sur le seul 15 mars 2007, et le
    meme jour recalcule par l'autre chemin changeait de valeur.
    """
    jour = dt.date(2026, 3, 20)
    # **Exactement trente jours avant le jour vise.** C'est la seule date qui
    # distingue les deux versions : un prix du 18 fevrier vaut jusqu'au 19 mars avec
    # une fenetre de trente jours (18 fevrier inclus), et jusqu'au 20 mars avec la
    # fenetre de trente et un jours qu'avait le chemin en masse. Un premier essai de
    # ce test avait pris le 19 fevrier -- a vingt-neuf jours -- et passait donc avec
    # le bug en place : un test qui n'echoue pas contre le code fautif ne prouve rien.
    limite = dt.datetime(2026, 2, 18, 10, tzinfo=PARIS)
    recent = dt.datetime(2026, 3, 18, 10, tzinfo=PARIS)
    stations, lignes = un_departement(combien=6, prix_eur=1.700, instant=recent)
    anciennes, prix_anciens = un_departement(
        combien=6, prix_eur=1.500, instant=limite, premier_id=13009001
    )

    connexion = ouvrir(base)
    try:
        charger_tout(connexion, limite, anciennes, prix_anciens)
        charger_tout(connexion, recent, stations, lignes, sha="b" * 64)

        agregats.calculer_periode(connexion, jour, jour)
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT stations, exclus, prix_min, prix_median, prix_max "
                "FROM marts.agregat_prix_jour "
                "WHERE jour = %s AND dimension = 'france' AND carburant = 'gazole'",
                (jour,),
            )
            en_masse = curseur.fetchone()

        with connexion.transaction(), connexion.cursor() as curseur:
            curseur.execute("DELETE FROM marts.agregat_prix_jour")
        agregats.calculer_agregats(connexion, [jour])
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT stations, exclus, prix_min, prix_median, prix_max "
                "FROM marts.agregat_prix_jour "
                "WHERE jour = %s AND dimension = 'france' AND carburant = 'gazole'",
                (jour,),
            )
            jour_par_jour = curseur.fetchone()
    finally:
        connexion.close()

    assert en_masse == jour_par_jour, (
        f"les deux chemins divergent : en masse {en_masse}, jour par jour {jour_par_jour}"
    )


@sans_base
@pytest.mark.parametrize(
    ("mad", "ecart"),
    [
        (0.06, 0.30),  # pile au seuil : 5 x 0,06 = 0,30, donc pas suspect
        (0.06, 0.31),  # juste au-dessus
        (0.0, 0.25),  # plancher : 5 x 0,05 = 0,25, pile au seuil
        (0.0, 0.26),
        (0.12, 0.60),
        (0.12, 0.61),
    ],
)
def test_sql_et_python_jugent_pareil_au_seuil_exact(base: str, mad: float, ecart: float) -> None:
    """Au seuil **exact**, pas seulement a ses abords.

    L'audit du 26/11/2026 a trouve deux divergences sur 4 060 cas tires au sort,
    toutes deux pile au seuil : `abs(1.8 - 1.5)` vaut `0.30000000000000004` en
    flottant et `0.30` en `numeric`. Le test precedent ne regardait qu'a 0,04 du
    seuil et ne pouvait pas le voir. Le code Python calcule desormais en `Decimal`.
    """
    mediane, stations = 1.500, 10
    connexion = ouvrir(base)
    try:
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT marts.est_suspect(%s::numeric, %s::numeric, %s::numeric, %s::integer)",
                (round(mediane + ecart, 10), mediane, mad, stations),
            )
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert ligne is not None
    cote_sql = bool(ligne[0])
    cote_python = aberrants.est_suspect(
        round(mediane + ecart, 10), mediane, mad, nombre_de_stations=stations
    )
    assert cote_sql == cote_python, (
        f"divergence a mad={mad}, ecart={ecart} : SQL {cote_sql}, Python {cote_python}"
    )


@pytest.mark.integration
def test_un_agregat_de_jour_a_venir_fait_echouer_le_controle(base: str) -> None:
    """Le controle qui manquait, et le defaut qu'il aurait vu.

    Le 28/11/2026, la base de production contenait des agregats jusqu'au
    25 decembre : l'amorcage avait demande « l'annee 2026 » en novembre, et le calcul
    en masse etend le dernier prix connu sur trente jours. L'anecdote du departement
    le moins cher de la semaine portait donc sur sept jours a venir -- sept copies du
    meme instantane fige. Aucun controle ne posait la question.
    """
    from carburant_etl.qualite.controles import CONTROLES, executer

    controle = next(c for c in CONTROLES if c.nom == "aucun_agregat_futur")
    assert controle.bloquant, "un agregat de jour a venir devient un chiffre affiche"

    with psycopg.connect(base, autocommit=True) as connexion:
        verdicts = {v.nom: v for v in executer(connexion, [controle])}
        assert verdicts["aucun_agregat_futur"].ok, "une base propre doit passer"

        demain = dt.datetime.now(tz=PARIS).date() + dt.timedelta(days=1)
        connexion.execute(
            "INSERT INTO marts.agregat_prix_jour "
            "(jour, carburant, dimension, valeur, stations, exclus, "
            " prix_min, prix_median, prix_moyen, prix_max) "
            "VALUES (%s, 'gazole', 'france', '', 100, 0, 1.800, 1.900, 1.900, 2.000)",
            (demain,),
        )
        verdicts = {v.nom: v for v in executer(connexion, [controle])}

    verdict = verdicts["aucun_agregat_futur"]
    assert not verdict.ok, "un agregat de demain doit faire echouer le controle"
    assert "jours a venir" in verdict.mesure
    assert str(demain) in verdict.mesure, "la mesure doit dire jusqu'ou va le probleme"


@pytest.mark.integration
def test_le_calcul_en_masse_ne_depasse_pas_aujourd_hui(base: str) -> None:
    """Demander l'annee entiere en novembre ne doit pas fabriquer du mois de decembre.

    La borne est posee dans `calculer_periode` et non chez l'appelant : tout appelant
    en beneficie, pas seulement la ligne de commande qui a cause le probleme.
    """
    from carburant_etl.chargement.agregats import calculer_periode, purger_le_futur

    aujourdhui = dt.datetime.now(tz=PARIS).date()
    with psycopg.connect(base, autocommit=True) as connexion:
        demain = aujourdhui + dt.timedelta(days=1)
        connexion.execute(
            "INSERT INTO marts.agregat_prix_jour "
            "(jour, carburant, dimension, valeur, stations, exclus, "
            " prix_min, prix_median, prix_moyen, prix_max) "
            "VALUES (%s, 'gazole', 'france', '', 100, 0, 1.800, 1.900, 1.900, 2.000)",
            (demain,),
        )
        assert purger_le_futur(connexion) == 1, "la purge doit retirer l'agregat de demain"

        # Une periode entierement a venir ne calcule rien, et ne plante pas.
        assert calculer_periode(connexion, demain, demain + dt.timedelta(days=30)) == 0

        # Une periode qui depasse aujourd'hui est ramenee : aucun jour a venir ne sort.
        calculer_periode(
            connexion, aujourdhui - dt.timedelta(days=2), aujourdhui + dt.timedelta(days=40)
        )
        ligne = connexion.execute(
            "SELECT count(*) FROM marts.agregat_prix_jour WHERE jour > %s", (aujourdhui,)
        ).fetchone()
    assert ligne is not None
    assert ligne[0] == 0, "aucun agregat ne doit porter un jour a venir"
