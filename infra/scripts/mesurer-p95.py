"""Mesure les temps de reponse de l'API, de l'interieur du reseau Docker.

Pourquoi de l'interieur : le critere de sortie du Jalon 3 porte sur l'API, pas sur
la liaison internet entre un runner GitHub et un VPS a Marseille. Mesure depuis le
conteneur de l'API, on obtient le temps que l'API met vraiment, Caddy et TLS exclus.
La mesure a travers Caddy est faite separement, et les deux sont rapportees.

S'execute dans l'image de l'API, qui a httpx. Aucun argument : les parcours sont
ecrits ici pour que la mesure soit reproductible a l'identique d'une fois sur
l'autre.

    python infra/scripts/mesurer-p95.py --base http://localhost:8000 --repetitions 20
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import httpx

# Dix villes reparties sur le territoire : une mesure prise uniquement a Marseille
# ne dirait rien des departements a forte densite de stations.
VILLES: list[tuple[str, float, float]] = [
    ("Marseille (Prado)", 43.2726, 5.3846),
    ("Paris (Bastille)", 48.8532, 2.3692),
    ("Lyon (Part-Dieu)", 45.7606, 4.8591),
    ("Toulouse (Capitole)", 43.6043, 1.4437),
    ("Lille (Grand-Place)", 50.6370, 3.0635),
    ("Bordeaux (Quinconces)", 44.8451, -0.5745),
    ("Nantes (Commerce)", 47.2135, -1.5565),
    ("Strasbourg (Kleber)", 48.5833, 7.7458),
    ("Clermont-Ferrand", 45.7772, 3.0870),
    ("Ajaccio", 41.9192, 8.7386),
]

CARBURANTS = ("gazole", "sp95", "e10", "e85")


@dataclass
class Mesures:
    """Les temps d'une route, en millisecondes."""

    route: str
    temps: list[float] = field(default_factory=list)
    echecs: int = 0
    causes: Counter[str] = field(default_factory=Counter)
    """Pourquoi les echecs ont echoue. Un script de mesure qui annonce « 20 echecs »
    sans dire lesquels oblige a tout refaire a la main pour le savoir."""

    def ajouter(self, debut: float, reponse: httpx.Response) -> None:
        if reponse.status_code >= 400:
            self.echecs += 1
            self.causes[f"HTTP {reponse.status_code}"] += 1
            return
        self.temps.append((time.perf_counter() - debut) * 1000)

    @property
    def p95(self) -> float:
        """Le 95e centile, par interpolation lineaire.

        `quantiles(n=20)[18]` donnerait le meme chiffre mais exige au moins
        20 points ; on prefere une formule qui marche aussi sur un petit
        echantillon plutot que de mentir sur la taille de l'echantillon.
        """
        if not self.temps:
            return float("nan")
        ordonnes = sorted(self.temps)
        if len(ordonnes) == 1:
            return ordonnes[0]
        position = 0.95 * (len(ordonnes) - 1)
        bas = int(position)
        haut = min(bas + 1, len(ordonnes) - 1)
        return ordonnes[bas] + (position - bas) * (ordonnes[haut] - ordonnes[bas])

    @property
    def _pourquoi(self) -> str:
        if not self.causes:
            return ""
        detail = ", ".join(f"{cause} x{nombre}" for cause, nombre in self.causes.most_common())
        return f"  [{self.echecs} echec(s) : {detail}]"

    def ligne(self) -> str:
        if not self.temps:
            return (
                f"{self.route:<34} aucune reponse exploitable"
                f"{self._pourquoi or f'  [{self.echecs} echec(s)]'}"
            )
        return (
            f"{self.route:<34} n={len(self.temps):<5} "
            f"mediane {statistics.median(self.temps):7.1f} ms  "
            f"p95 {self.p95:7.1f} ms  "
            f"max {max(self.temps):7.1f} ms" + self._pourquoi
        )


def _appeler(client: httpx.Client, mesures: Mesures, chemin: str, **params: Any) -> None:
    debut = time.perf_counter()
    try:
        reponse = client.get(chemin, params=params)
    except httpx.HTTPError as erreur:
        mesures.echecs += 1
        mesures.causes[type(erreur).__name__] += 1
        print(f"  echec sur {chemin} : {erreur}", file=sys.stderr)
        return
    mesures.ajouter(debut, reponse)


def mesurer(base: str, repetitions: int) -> list[Mesures]:
    """Joue les parcours et rend une mesure par route."""
    # Timeout genereux : on veut mesurer une lenteur, pas la transformer en echec.
    # Une route qui met huit secondes doit apparaitre dans le tableau, pas disparaitre.
    with httpx.Client(base_url=base, timeout=30.0) as client:
        # Une requete pour rien d'abord : la premiere paie l'ouverture du pool de
        # connexions a la base et faussait la mediane.
        client.get("/v1/sante")

        # Les noms de parametres de l'API sont verifies ici, avant de mesurer quoi que
        # ce soit. Sans ce garde-fou, une faute de frappe ferait repondre 422 a chaque
        # requete et le script rapporterait « aucune reponse exploitable » -- ce qui
        # ressemble a une panne de l'API alors que c'est la mesure qui est fausse.
        # Constate : la premiere version demandait `latitude`/`longitude` quand l'API
        # attend `lat`/`lon`.
        controle = client.get(
            "/v1/stations/proches",
            params={"lat": 43.2726, "lon": 5.3846, "carburant": "gazole", "rayon_km": 10},
        )
        if controle.status_code != 200:
            raise SystemExit(
                "La requete de controle a repondu "
                f"{controle.status_code} : {controle.text[:300]}\n"
                "Les noms de parametres de ce script ne correspondent plus a l'API."
            )

        proches = Mesures("/v1/stations/proches")
        meilleure = Mesures("/v1/stations/meilleure")
        fiche = Mesures("/v1/stations/{id}")
        historique = Mesures("/v1/stations/{id}/historique")
        tendances = Mesures("/v1/tendances")
        anecdotes = Mesures("/v1/anecdotes/du-jour")
        meta = Mesures("/v1/meta")
        sante = Mesures("/v1/sante")

        for tour in range(repetitions):
            for _nom, lat, lon in VILLES:
                carburant = CARBURANTS[tour % len(CARBURANTS)]
                _appeler(
                    client,
                    proches,
                    "/v1/stations/proches",
                    lat=lat,
                    lon=lon,
                    carburant=carburant,
                    rayon_km=10,
                )
                _appeler(
                    client,
                    meilleure,
                    "/v1/stations/meilleure",
                    lat=lat,
                    lon=lon,
                    carburant=carburant,
                    autonomie_km=60,
                )

        # La fiche et l'historique ont besoin d'un identifiant reel : on le prend
        # dans une recherche plutot que de le coder en dur, pour que la mesure
        # survive a une station qui ferme.
        autour = client.get(
            "/v1/stations/proches",
            params={"lat": 43.2726, "lon": 5.3846, "rayon_km": 10},
        )
        identifiants = [s["id"] for s in autour.json().get("stations", [])][:10] or [13008003]

        for _ in range(repetitions):
            for identifiant in identifiants:
                _appeler(client, fiche, f"/v1/stations/{identifiant}")
                _appeler(client, historique, f"/v1/stations/{identifiant}/historique", jours=90)

        for tour in range(repetitions):
            carburant = CARBURANTS[tour % len(CARBURANTS)]
            _appeler(client, tendances, "/v1/tendances", carburant=carburant, jours=365)
            _appeler(client, anecdotes, "/v1/anecdotes/du-jour", carburant=carburant)
            _appeler(client, meta, "/v1/meta")
            _appeler(client, sante, "/v1/sante")

    return [proches, meilleure, fiche, historique, tendances, anecdotes, meta, sante]


def principal() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--base", default="http://localhost:8000")
    analyseur.add_argument("--repetitions", type=int, default=20)
    analyseur.add_argument(
        "--budget-ms",
        type=float,
        default=300.0,
        help="Budget p95 de /v1/stations/proches. Depasse, le script echoue.",
    )
    arguments = analyseur.parse_args()

    print(f"Base mesuree : {arguments.base}")
    print(f"{arguments.repetitions} tours, {len(VILLES)} villes\n")

    resultats = mesurer(arguments.base, arguments.repetitions)
    for mesure in resultats:
        print(mesure.ligne())

    proches = resultats[0]
    if not proches.temps:
        print("\nAucune mesure exploitable sur /v1/stations/proches.", file=sys.stderr)
        return 1
    print(
        f"\nCritere de sortie du Jalon 3 : p95 de /v1/stations/proches "
        f"= {proches.p95:.1f} ms pour un budget de {arguments.budget_ms:.0f} ms."
    )
    if proches.p95 > arguments.budget_ms:
        print("Budget depasse.", file=sys.stderr)
        return 1
    print("Budget respecte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
