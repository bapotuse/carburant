"""Version et metadonnees exposees par l'OpenAPI."""

from __future__ import annotations

from typing import Final

VERSION: Final = "0.1.0"
PREFIXE: Final = "/v1"

TITRE: Final = "API Carburant"
DESCRIPTION: Final = """\
Prix des carburants en France, collectes toutes les 15 minutes depuis le flux ouvert
de la DGCCRF, nettoyes et historises.

**Toutes les unites sont dans les noms de champs** : `prix_eur_l`, `distance_km`,
`co2_kg`. Un prix est toujours accompagne de sa date de mise a jour et de sa classe de
fraicheur : la source publie la date du dernier *changement* de prix, pas celle du
dernier controle.

Sources et licences : prix DGCCRF (Licence Ouverte 2.0), facteurs d'emission Base
Carbone ADEME (Licence Ouverte), geocodage Geoplateforme IGN.
"""
