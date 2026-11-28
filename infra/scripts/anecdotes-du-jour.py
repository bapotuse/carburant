"""Imprime la reponse de `/v1/anecdotes/du-jour`, pour la lire sur les vraies donnees.

L'anecdote « jour de la semaine historiquement le moins cher » exige cinquante-deux
semaines d'historique pour chacun des sept jours. Elle etait donc indisponible
partout, et sa seule verification possible etait un jeu de test synthetique. Avec
vingt ans en base sur le VPS, elle doit enfin sortir : ce script sert a la lire.

S'execute dans le conteneur de l'API, qui n'a besoin que de la bibliotheque standard.
"""

from __future__ import annotations

import json
import sys
import urllib.request

CARBURANTS = ("gazole", "e85")


def principal() -> int:
    for carburant in CARBURANTS:
        url = f"http://localhost:8000/v1/anecdotes/du-jour?carburant={carburant}"
        print(f"=== {carburant} ===")
        try:
            with urllib.request.urlopen(url, timeout=60) as reponse:
                charge = json.load(reponse)
        except OSError as erreur:
            print(f"echec : {erreur}", file=sys.stderr)
            return 1
        print(json.dumps(charge, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
