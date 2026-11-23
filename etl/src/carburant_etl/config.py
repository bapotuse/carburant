"""Configuration de l'ETL, lue dans l'environnement.

Aucun secret en dur, aucune valeur par defaut qui pointerait vers la production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

URL_FLUX_EXPORT: Final = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
    "/prix-des-carburants-en-france-flux-instantane-v2/exports/json"
)
"""Export complet du flux v2. `exports/` et non `records/`, qui est pagine et plafonne.
Le json est retenu plutot que le parquet, pourtant plus leger (2,8 Mo contre 4,6) :
c'est le seul format ou les champs multivalues -- `services_service`,
`carburants_disponibles` -- sont de vraies listes, et non des chaines a redecouper.
L'ecart de poids est absorbe par la compression a la volee (docs/reconnaissance.md
section 1.1)."""

URL_AMONT_INSTANTANE: Final = "https://donnees.roulez-eco.fr/opendata/instantane_ruptures"
"""Source amont, gardee en repli : data.economie a deja connu des indisponibilites."""

URL_AMONT_ANNEE: Final = "https://donnees.roulez-eco.fr/opendata/annee/{annee}"
"""Archives annuelles, depuis 2007."""

URL_ADEME_LIGNES: Final = "https://data.ademe.fr/data-fair/api/v1/datasets/base-carboner/lines"
"""Base Carbone de l'ADEME. Le portail a migre d'Opendatasoft vers Data Fair :
l'ancienne API Explore v2.1 repond HTTP 410 (docs/reconnaissance.md section 3)."""

ENCODAGE_SOURCE: Final = "latin-1"
"""Les XML de roulez-eco declarent ISO-8859-1, instantane comme archives."""

PREMIERE_ANNEE_ARCHIVE: Final = 2007
ANNEE_BASCULE_EUROS: Final = 2022
"""Les archives sont en milliemes d'euro jusqu'a 2021 et en euros depuis 2022. On ne
s'appuie pas sur cette annee pour convertir -- la regle `valeur > 20 -> /1000` marche
sur les deux eres -- mais elle documente la bascule."""

EMPRISE_LATITUDE: Final = (41.0, 51.5)
EMPRISE_LONGITUDE: Final = (-5.5, 10.0)
"""Emprise France metropolitaine + Corse. Le flux ne contient aucune station en DROM
(0 code en 97x ou 98x). Les archives, elles, en contiennent, ainsi que de vraies
aberrations : une latitude de 62,6 degres, au nord de la Norvege."""


@dataclass(frozen=True, slots=True)
class Config:
    """Configuration effective d'une execution."""

    database_url: str
    user_agent: str
    repertoire_brut: Path
    retention_jours: int
    healthcheck_url: str | None

    @classmethod
    def depuis_environnement(cls) -> Self:
        """Construit la configuration a partir des variables d'environnement."""
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError(
                "DATABASE_URL absente. Copier .env.example en .env et la renseigner."
            )
        return cls(
            database_url=url,
            user_agent=os.environ.get(
                "ETL_USER_AGENT",
                "carburant/0.1 (+https://github.com/bapotuse/carburant)",
            ),
            repertoire_brut=Path(os.environ.get("ETL_REPERTOIRE_BRUT", "data/raw")),
            retention_jours=int(os.environ.get("ETL_RETENTION_JOURS", "14")),
            healthcheck_url=os.environ.get("HEALTHCHECK_URL") or None,
        )
