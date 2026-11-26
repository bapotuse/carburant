"""Detection des prix aberrants : bornes absolues, puis ecart a la mediane du departement.

Deux mecanismes distincts, qui ne font pas la meme chose :

- **Bornes absolues par carburant** : hors bornes, ce n'est pas un prix. Rejete et
  compte. Elles ont attrape les 4 vraies erreurs de saisie du 23/11/2026 -- trois E85 a
  1,99 EUR et un a 2,249 EUR, quand le p99,9 de l'E85 est a 1,313 : quelqu'un avait
  saisi le prix du SP95 dans la case E85.
- **Ecart relatif a la mediane departementale du jour** : signale un prix atypique.
  Conserve, affiche, mais exclu des classements et des moyennes. Les prix ainsi
  signales sont le plus souvent de **vrais** prix eleves : L'Ile-d'Yeu, Val-d'Isere,
  Saint-Tropez, Cauterets. On ne les rejette pas.

Le plancher de MAD est indispensable. Sans lui, la regle signale 8 a 19 % des prix,
parce que la MAD departementale descend a 0,0005 EUR la ou beaucoup de stations
affichent le meme prix (gazole en Haute-Corse). Avec un plancher a 0,05 EUR et k = 5,
elle signale 0,4 a 2,5 % des prix. Mesures dans docs/reconnaissance.md section 1.10.
"""

from __future__ import annotations

import statistics as stats
from decimal import Decimal
from typing import Final

from carburant_etl.carburants import CodeCarburant, est_dans_les_bornes

PLANCHER_MAD: Final = 0.05
"""Plancher de la MAD, en euros par litre. Voir l'explication du module."""

FACTEUR_MAD: Final = 5.0
"""Nombre de MAD au dela duquel un prix est signale comme suspect."""

MIN_STATIONS_DEPARTEMENT: Final = 5
"""En dessous, le departement n'a pas assez de stations pour une mediane fiable."""


def dans_les_bornes(code: CodeCarburant, prix: float) -> bool:
    """Le prix est-il un prix plausible pour ce carburant ? Sinon : rejete et compte."""
    return est_dans_les_bornes(code, prix)


def _decimal(valeur: float) -> Decimal:
    """Un flottant, lu comme PostgreSQL lirait le litteral correspondant.

    `Decimal(str(x))` et non `Decimal(x)` : le second garderait l'approximation
    binaire du flottant, ce qu'on cherche justement a eviter.
    """
    return Decimal(str(valeur))


def mediane_et_mad(prix: list[float]) -> tuple[float, float]:
    """Mediane et ecart absolu median d'une serie de prix.

    La MAD renvoyee n'est pas plancheree : c'est la vraie dispersion observee, utile
    pour les rapports de qualite. Le plancher s'applique dans `est_suspect`.
    """
    if not prix:
        raise ValueError("serie de prix vide")
    mediane = stats.median(prix)
    mad = stats.median([abs(p - mediane) for p in prix])
    return mediane, mad


def est_suspect(
    prix: float,
    mediane_departement: float,
    mad_departement: float,
    *,
    nombre_de_stations: int,
) -> bool:
    """Ce prix s'ecarte-t-il trop de la mediane de son departement ?

    Renvoie False si le departement compte moins de `MIN_STATIONS_DEPARTEMENT`
    stations pour ce carburant : on ne juge pas un prix sur trois voisins.

    **Le calcul se fait en `Decimal`, pas en flottant**, pour rendre exactement le
    meme verdict que `marts.est_suspect`, qui travaille en `numeric`. Mesure de
    l'audit du 26/11/2026 : sur 4 060 cas tires au sort, deux divergeaient, tous
    deux pile au seuil -- `abs(1.8 - 1.5)` vaut `0.30000000000000004` en flottant et
    `0.30` en `numeric`, pour un seuil de `5 x 0.06 = 0.30`. Une regle dont la base
    et le code ne donnent pas le meme verdict n'est pas une regle.
    """
    if nombre_de_stations < MIN_STATIONS_DEPARTEMENT:
        return False
    ecart = abs(_decimal(prix) - _decimal(mediane_departement))
    echelle = max(_decimal(mad_departement), _decimal(PLANCHER_MAD))
    return ecart > _decimal(FACTEUR_MAD) * echelle


def ecart_en_mad(prix: float, mediane_departement: float, mad_departement: float) -> float:
    """Ecart a la mediane, exprime en nombre de MAD plancherees.

    Stocke a cote du prix suspect : il explique *pourquoi* il a ete signale, ce qui
    rend le signalement verifiable plutot que magique.
    """
    ecart = abs(_decimal(prix) - _decimal(mediane_departement))
    return float(ecart / max(_decimal(mad_departement), _decimal(PLANCHER_MAD)))
