"""Historisation des facteurs d'emission dans `marts.ref_facteur_emission`.

Jamais de mise a jour en place : une nouvelle version de la Base Carbone donne une
nouvelle ligne. Relancer la recuperation sur la meme version n'en cree aucune.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from carburant_etl.sources.ademe import Facteur

journal = logging.getLogger("carburant.facteurs")


@dataclass(frozen=True, slots=True)
class ResultatFacteurs:
    """Ce qu'une recuperation a ajoute."""

    nouveaux: int
    deja_connus: int
    version: str


_INSERER = """
INSERT INTO marts.ref_facteur_emission
    (carburant, element_ademe, nom_base, nom_attribut, valeur, unite,
     localisation, statut, date_modification, periode_validite, version_base, url)
VALUES (%(carburant)s, %(element_ademe)s, %(nom_base)s, %(nom_attribut)s, %(valeur)s,
        %(unite)s, %(localisation)s, %(statut)s, %(date_modification)s,
        %(periode_validite)s, %(version_base)s, %(url)s)
ON CONFLICT (carburant, version_base, element_ademe) DO NOTHING
"""


def charger(
    connexion: psycopg.Connection[tuple[object, ...]], facteurs: Sequence[Facteur]
) -> ResultatFacteurs:
    """Insere les facteurs absents. Idempotent pour une version donnee."""
    if not facteurs:
        raise ValueError("aucun facteur a charger")
    nouveaux = 0
    with connexion.transaction(), connexion.cursor() as curseur:
        for facteur in facteurs:
            curseur.execute(
                _INSERER,
                {
                    "carburant": facteur.carburant,
                    "element_ademe": facteur.element_ademe,
                    "nom_base": facteur.nom_base,
                    "nom_attribut": facteur.nom_attribut,
                    "valeur": facteur.valeur,
                    "unite": facteur.unite,
                    "localisation": facteur.localisation,
                    "statut": facteur.statut,
                    "date_modification": facteur.date_modification,
                    "periode_validite": facteur.periode_validite,
                    "version_base": facteur.version_base,
                    "url": facteur.url,
                },
            )
            nouveaux += curseur.rowcount
    version = facteurs[0].version_base
    journal.info(
        "facteurs d emission : %d nouveau(x), %d deja connu(s), version %s",
        nouveaux,
        len(facteurs) - nouveaux,
        version,
    )
    return ResultatFacteurs(
        nouveaux=nouveaux, deja_connus=len(facteurs) - nouveaux, version=version
    )
