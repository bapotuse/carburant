"""Le coût réel d'un plein, détour compris.

C'est le cœur du projet, et son idée tient en une phrase : **la station la moins
chère n'est pas toujours la moins chère.** Faire six kilomètres de plus pour gagner
trois centimes au litre coûte plus que ça ne rapporte, et personne ne fait ce calcul
de tête devant une pompe.

    cout_reel = prix x litres  +  prix x (2 x distance x consommation / 100)
                ^^^^^^^^^^^^^     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                le plein           le carburant brule pour l'aller-retour

**Trois hypothèses, assumées et affichées** plutôt que cachées dans le code :

1. **Aller-retour.** On repart d'où on vient. C'est faux pour qui fait le plein sur
   sa route, et juste pour qui fait un détour exprès — le cas où la question se pose.
2. **Le carburant du trajet est valorisé au prix de la station.** Approximation :
   le trajet se fait avec ce qui reste dans le réservoir, acheté ailleurs. Mais
   raisonner autrement demanderait de connaître le prix payé la fois d'avant.
3. **La distance routière est estimée** à partir de la distance à vol d'oiseau,
   multipliée par un facteur de détour. Un service d'itinéraire donnerait la vraie,
   mais pour les seuls meilleurs candidats et au prix d'un appel réseau par station.

Ces trois hypothèses sont affichées à côté du résultat sur le site : un chiffre
qu'on ne peut pas expliquer ne mérite pas d'être affiché.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

FACTEUR_DETOUR: Final = 1.3
"""Rapport entre distance routière et distance à vol d'oiseau.

Valeur de départ, **à calibrer** contre le service d'itinéraire de la Géoplateforme
(noté dans `docs/a-verifier.md`). Elle n'est pas neutre : à 10 km à vol d'oiseau,
1,3 ajoute 6 km d'aller-retour, soit environ 0,80 EUR de carburant brûlé. Un facteur
trop faible ferait recommander des stations trop lointaines.
"""

MARGE_AUTONOMIE: Final = 0.8
"""On ne propose pas une station à l'exacte limite du réservoir.

Vingt pour cent de marge : l'autonomie affichée par un tableau de bord est
optimiste, et tomber en panne en suivant notre conseil serait le pire résultat
possible.
"""

LITRES_PAR_DEFAUT: Final = 40.0
"""Volume par défaut d'un plein, en litres.

**Ce n'est pas une moyenne française mesurée**, c'est la valeur pré-remplie d'un
champ que l'utilisateur modifie. Elle n'est jamais présentée comme un fait. À
remplacer par une donnée sourcée si on veut un jour l'afficher comme telle
(`docs/a-verifier.md`).
"""

CONSOMMATION_PAR_DEFAUT: Final = 7.0
"""Consommation par défaut, en litres aux 100 km. Même statut que `LITRES_PAR_DEFAUT`."""


class EntreeInvalide(ValueError):
    """Un paramètre du calcul n'a pas de sens physique."""


@dataclass(frozen=True, slots=True)
class Detail:
    """Le coût d'un plein dans une station, décomposé pour être vérifiable."""

    prix_eur_l: float
    distance_km: float
    """Distance routière estimée, aller simple."""
    litres: float
    consommation_l_100km: float

    @property
    def cout_plein_eur(self) -> float:
        """Ce que coûte le carburant qu'on met dans le réservoir."""
        return self.prix_eur_l * self.litres

    @property
    def litres_du_detour(self) -> float:
        """Le carburant brûlé pour aller à cette station et en revenir."""
        return 2 * self.distance_km * self.consommation_l_100km / 100

    @property
    def cout_detour_eur(self) -> float:
        """Ce que coûte ce carburant-là, au prix de la station."""
        return self.prix_eur_l * self.litres_du_detour

    @property
    def cout_reel_eur(self) -> float:
        """Le total : le plein plus le détour."""
        return self.cout_plein_eur + self.cout_detour_eur


def verifier(
    *, prix_eur_l: float, distance_km: float, litres: float, consommation_l_100km: float
) -> None:
    """Refuse ce qui n'a pas de sens physique, en le disant.

    Mieux vaut une erreur lisible qu'un coût négatif qui remonterait jusqu'à
    l'affichage sans que personne ne s'en aperçoive.
    """
    if prix_eur_l <= 0:
        raise EntreeInvalide(f"prix nul ou negatif : {prix_eur_l}")
    if distance_km < 0:
        raise EntreeInvalide(f"distance negative : {distance_km}")
    if litres <= 0:
        raise EntreeInvalide(f"volume nul ou negatif : {litres}")
    if consommation_l_100km < 0:
        raise EntreeInvalide(f"consommation negative : {consommation_l_100km}")


def distance_routiere(distance_vol_oiseau_km: float, *, facteur: float = FACTEUR_DETOUR) -> float:
    """Estime la distance par la route à partir de la distance géodésique."""
    if distance_vol_oiseau_km < 0:
        raise EntreeInvalide(f"distance negative : {distance_vol_oiseau_km}")
    return distance_vol_oiseau_km * facteur


def atteignable(
    distance_routiere_km: float, autonomie_km: float, *, marge: float = MARGE_AUTONOMIE
) -> bool:
    """La station est-elle dans le rayon qu'on ose recommander ?

    Une autonomie nulle ou négative ne rend rien atteignable : c'est le cas du
    conducteur déjà en panne, pour lequel il n'y a pas de bonne réponse à donner.
    """
    if autonomie_km <= 0:
        return False
    return distance_routiere_km <= autonomie_km * marge


def detail(
    *,
    prix_eur_l: float,
    distance_km: float,
    litres: float = LITRES_PAR_DEFAUT,
    consommation_l_100km: float = CONSOMMATION_PAR_DEFAUT,
) -> Detail:
    """Le coût réel d'un plein dans cette station, décomposé."""
    verifier(
        prix_eur_l=prix_eur_l,
        distance_km=distance_km,
        litres=litres,
        consommation_l_100km=consommation_l_100km,
    )
    return Detail(
        prix_eur_l=prix_eur_l,
        distance_km=distance_km,
        litres=litres,
        consommation_l_100km=consommation_l_100km,
    )


def economie(meilleure: Detail, reference: Detail) -> float:
    """Ce qu'on gagne à aller à `meilleure` plutôt qu'à `reference`.

    `reference` est la station atteignable **la plus proche** : c'est ce que ferait
    quelqu'un qui ne réfléchit pas. L'économie ne peut pas être négative — si la
    plus proche est aussi la meilleure, elle vaut zéro et on le dit, plutôt que
    d'inventer un gain.
    """
    return max(0.0, reference.cout_reel_eur - meilleure.cout_reel_eur)
