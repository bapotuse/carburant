"""Tests de la limitation de débit.

Le temps est injecté : un test qui attend une minute pour vérifier qu'une fenêtre
s'est écoulée n'est pas un test, c'est une pause.
"""

from __future__ import annotations

import pytest
from carburant_api.limite import (
    FENETRE_SECONDES,
    Limiteur,
    MiddlewareLimite,
    adresse_cliente,
    limite_configuree,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_sous_la_limite_tout_passe() -> None:
    limiteur = Limiteur(limite=5)
    for i in range(5):
        autorise, _ = limiteur.autoriser("1.2.3.4", instant=float(i))
        assert autorise, f"la requete {i + 1} sur 5 aurait du passer"


def test_la_limite_est_atteinte_a_la_bonne_requete() -> None:
    """La sixième requête sur une limite de cinq est refusée, pas la cinquième."""
    limiteur = Limiteur(limite=5)
    for i in range(5):
        assert limiteur.autoriser("1.2.3.4", instant=float(i))[0]
    autorise, reessai = limiteur.autoriser("1.2.3.4", instant=5.0)
    assert not autorise
    assert reessai >= 1, "un refus doit toujours dire quand reessayer"


def test_les_adresses_sont_independantes() -> None:
    """Un client bruyant ne doit pas bloquer les autres."""
    limiteur = Limiteur(limite=2)
    assert limiteur.autoriser("1.1.1.1", instant=0.0)[0]
    assert limiteur.autoriser("1.1.1.1", instant=0.0)[0]
    assert not limiteur.autoriser("1.1.1.1", instant=0.0)[0]
    assert limiteur.autoriser("2.2.2.2", instant=0.0)[0], "l'autre adresse est innocente"


def test_apres_deux_fenetres_le_compteur_est_remis_a_zero() -> None:
    limiteur = Limiteur(limite=3)
    for _ in range(3):
        limiteur.autoriser("1.2.3.4", instant=0.0)
    assert not limiteur.autoriser("1.2.3.4", instant=1.0)[0]
    plus_tard = 2 * FENETRE_SECONDES + 1
    assert limiteur.autoriser("1.2.3.4", instant=plus_tard)[0]


def test_la_fenetre_glissante_ne_laisse_pas_passer_le_double() -> None:
    """Le piège qu'une fenêtre fixe ne voit pas.

    Avec une fenêtre fixe, saturer la fin d'une minute puis le début de la suivante
    fait passer deux fois la limite en quelques secondes. Ici, la fenêtre précédente
    pèse encore presque tout son poids juste après la bascule, donc les premières
    requêtes de la nouvelle fenêtre sont refusées.
    """
    limiteur = Limiteur(limite=10)
    # On sature la fin de la première fenêtre.
    for _ in range(10):
        limiteur.autoriser("1.2.3.4", instant=FENETRE_SECONDES - 1)
    # Une seconde plus tard, la fenêtre a basculé mais la précédente pèse 59/60.
    autorise, _ = limiteur.autoriser("1.2.3.4", instant=FENETRE_SECONDES + 0.5)
    assert not autorise, "une fenetre fixe aurait laisse repartir a zero"
    # Le budget revient progressivement, pas d'un coup : une demi-fenêtre après la
    # fin de la fenêtre saturée, la précédente ne pèse plus que la moitié.
    # (La première requête était à 59 s, donc la bascule se fait à 119 s.)
    assert not limiteur.autoriser("1.2.3.4", instant=119.0)[0], (
        "a la bascule exacte, la fenetre pleine compte encore entierement"
    )
    assert limiteur.autoriser("1.2.3.4", instant=149.0)[0], (
        "a mi-fenetre, la moitie du budget doit etre revenue"
    )


def test_la_memoire_est_bornee() -> None:
    """Sans borne, des adresses tournantes feraient tomber le processus."""
    limiteur = Limiteur(limite=100, adresses_max=100)
    for i in range(400):
        limiteur.autoriser(f"10.0.{i // 256}.{i % 256}", instant=float(i))
    assert limiteur.adresses_suivies <= 100, "le dictionnaire doit rester borne"


def test_adresse_derriere_le_proxy() -> None:
    """Caddy pose `X-Forwarded-For` ; on prend le client d'origine, pas le proxy."""
    assert adresse_cliente({"x-forwarded-for": "203.0.113.7"}, "172.18.0.5") == "203.0.113.7"
    assert (
        adresse_cliente({"x-forwarded-for": "203.0.113.7, 172.18.0.2"}, "172.18.0.5")
        == "203.0.113.7"
    )
    assert adresse_cliente({}, "172.18.0.5") == "172.18.0.5", "sans proxy, l'adresse du pair"


def test_limite_configuree_tolere_une_valeur_absurde(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une variable d'environnement mal saisie ne doit pas empêcher l'API de démarrer."""
    monkeypatch.setenv("API_LIMITE_PAR_MINUTE", "beaucoup")
    assert limite_configuree() == 120
    monkeypatch.setenv("API_LIMITE_PAR_MINUTE", "0")
    assert limite_configuree() == 1, "une limite nulle bloquerait tout"
    monkeypatch.setenv("API_LIMITE_PAR_MINUTE", "7")
    assert limite_configuree() == 7


def _app_minimale(limiteur: Limiteur) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/essai")
    async def essai() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/v1/sante")
    async def sante() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(MiddlewareLimite, limiteur=limiteur)
    return app


def test_le_middleware_rend_un_problem_json() -> None:
    client = TestClient(_app_minimale(Limiteur(limite=2)))
    assert client.get("/v1/essai").status_code == 200
    assert client.get("/v1/essai").status_code == 200

    refus = client.get("/v1/essai")
    assert refus.status_code == 429
    assert refus.headers["content-type"].startswith("application/problem+json")
    assert int(refus.headers["Retry-After"]) >= 1
    corps = refus.json()
    assert corps["status"] == 429
    assert corps["instance"] == "/v1/essai"
    assert "2 requetes par minute" in corps["detail"], "le message doit dire la limite"


def test_la_sante_n_est_jamais_limitee() -> None:
    """Un excès de trafic ne doit pas faire déclarer le conteneur malade."""
    client = TestClient(_app_minimale(Limiteur(limite=1)))
    assert client.get("/v1/essai").status_code == 200
    assert client.get("/v1/essai").status_code == 429
    for _ in range(5):
        assert client.get("/v1/sante").status_code == 200


def test_la_boucle_locale_sans_proxy_n_est_pas_limitee() -> None:
    """La sonde Docker et les scripts de maintenance passent toujours.

    `TestClient` se presente par defaut comme `testclient` et non comme une adresse
    de boucle locale -- ce qui est heureux, car cela prouve que les douze tests
    ci-dessus exercent bien le limiteur et ne beneficient pas de cette exemption.
    On force donc l'adresse du pair ici.
    """
    client = TestClient(_app_minimale(Limiteur(limite=2)), client=("127.0.0.1", 50000))
    for _ in range(10):
        assert client.get("/v1/essai").status_code == 200


def test_la_boucle_locale_avec_un_proxy_est_limitee() -> None:
    """Le trafic public arrive toujours avec un `X-Forwarded-For`.

    C'est ce qui empeche un client public de profiter de l'exemption : des qu'il
    passe par Caddy, l'en-tete est present et on retombe dans le cas general.
    """
    client = TestClient(_app_minimale(Limiteur(limite=2)), client=("127.0.0.1", 50000))
    entetes = {"X-Forwarded-For": "203.0.113.7"}
    assert client.get("/v1/essai", headers=entetes).status_code == 200
    assert client.get("/v1/essai", headers=entetes).status_code == 200
    assert client.get("/v1/essai", headers=entetes).status_code == 429
