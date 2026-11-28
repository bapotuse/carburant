"""Limitation de débit par adresse IP.

Un service public gratuit finit toujours par être aspiré. Sans garde-fou, une seule
boucle mal écrite peut saturer le VPS — qui a 10 Go de RAM et partage son CPU — et
rendre le site indisponible pour tout le monde.

**Pourquoi un compteur en mémoire et pas Redis.** Il n'y a qu'un conteneur d'API sur
le VPS : un compteur partagé n'aurait rien à partager. Ajouter un service se
justifie par un besoin, pas par principe. Le jour où l'API tournera en plusieurs
exemplaires, cette classe sera remplacée, et c'est tout — c'est la même décision que
pour le cache du géocodage.

**Fenêtre glissante approchée, pas fenêtre fixe.** Une fenêtre fixe laisse passer
deux fois la limite à cheval sur sa frontière : 120 requêtes à 11 h 59 min 59 s puis
120 à 12 h 00 min 00 s. On pondère donc la fenêtre précédente par ce qu'il reste de
la courante, ce qui lisse la bordure pour le coût d'un entier de plus par adresse.

**La mémoire est bornée.** Sans cela, une attaque depuis des adresses tournantes
remplirait le dictionnaire jusqu'à faire tomber le processus — la limitation de
débit deviendrait elle-même le vecteur de déni de service.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

journal = logging.getLogger("carburant.limite")

LIMITE_PAR_DEFAUT: Final = 120
"""Requêtes par minute et par adresse. Le site en fait trois ou quatre par page ;
un humain ne s'en approchera jamais, un script mal écrit si."""

FENETRE_SECONDES: Final = 60.0

ADRESSES_MAX: Final = 20_000
"""Au-delà, les plus anciennes sont oubliées. Borne la mémoire du compteur."""

BOUCLE_LOCALE: Final = frozenset({"127.0.0.1", "::1"})
"""Adresses de boucle locale, exemptées quand la requête n'a **pas** traversé le proxy.

Ce n'est pas un trou : l'API ne publie aucun port, donc tout trafic public passe par
Caddy, qui se présente avec l'adresse de **son** conteneur et pose un
`X-Forwarded-For`. Une requête qui arrive sans cet en-tête depuis la boucle locale
vient donc de l'intérieur du conteneur de l'API lui-même : la sonde de Docker, ou un
script de maintenance. Une requête publique ne peut pas se faire passer pour
celle-là, puisqu'elle arrive forcément avec un `X-Forwarded-For`, qui la ramène au
cas général.
"""


@dataclass
class _Compteur:
    """L'état d'une adresse : deux fenêtres et leur début."""

    debut: float
    courante: int = 0
    precedente: int = 0


@dataclass
class Limiteur:
    """Compteur à fenêtre glissante approchée, par adresse."""

    limite: int = LIMITE_PAR_DEFAUT
    fenetre: float = FENETRE_SECONDES
    adresses_max: int = ADRESSES_MAX
    _compteurs: dict[str, _Compteur] = field(default_factory=dict)

    @property
    def adresses_suivies(self) -> int:
        """Combien d'adresses le compteur garde en mémoire. Pour les tests et les journaux."""
        return len(self._compteurs)

    def autoriser(self, adresse: str, *, instant: float | None = None) -> tuple[bool, int]:
        """La requête passe-t-elle ? Renvoie (autorisée, secondes avant réessai).

        `instant` n'existe que pour les tests : le temps est une dépendance comme
        une autre, et un test qui dort une minute n'est pas un test.
        """
        maintenant = instant if instant is not None else time.monotonic()
        compteur = self._compteurs.get(adresse)

        if compteur is None:
            self._faire_de_la_place()
            self._compteurs[adresse] = _Compteur(debut=maintenant, courante=1)
            return True, 0

        ecoule = maintenant - compteur.debut
        if ecoule >= 2 * self.fenetre:
            # Plus aucune trace utile : on repart de zéro.
            compteur.debut, compteur.courante, compteur.precedente = maintenant, 1, 0
            return True, 0
        if ecoule >= self.fenetre:
            compteur.debut += self.fenetre
            compteur.precedente, compteur.courante = compteur.courante, 0
            ecoule -= self.fenetre

        # Le poids de la fenêtre précédente décroît à mesure qu'on avance dans la
        # courante : à mi-fenêtre, elle compte pour moitié.
        poids = 1.0 - (ecoule / self.fenetre)
        estime = compteur.precedente * poids + compteur.courante

        if estime >= self.limite:
            return False, max(1, int(self.fenetre - ecoule))

        compteur.courante += 1
        return True, 0

    def _faire_de_la_place(self) -> None:
        """Oublie les adresses les plus anciennes quand le dictionnaire est plein.

        Sans cette borne, une attaque depuis des adresses tournantes ferait du
        limiteur lui-même un vecteur de déni de service.
        """
        if len(self._compteurs) < self.adresses_max:
            return
        a_oublier = sorted(self._compteurs.items(), key=lambda paire: paire[1].debut)
        for adresse, _ in a_oublier[: self.adresses_max // 10]:
            del self._compteurs[adresse]
        journal.info("limiteur : %d adresses oubliees", self.adresses_max // 10)


def limite_configuree() -> int:
    """Lue dans l'environnement, pour pouvoir la desserrer sans redéployer d'image."""
    try:
        return max(1, int(os.environ.get("API_LIMITE_PAR_MINUTE", str(LIMITE_PAR_DEFAUT))))
    except ValueError:
        return LIMITE_PAR_DEFAUT


def adresse_cliente(entetes: Mapping[str, str], repli: str) -> str:
    """L'adresse du client, derrière le reverse proxy.

    Caddy pose `X-Forwarded-For`. On prend **la première** valeur, qui est le client
    d'origine, et on ne lit cet en-tête que parce que l'API n'est joignable que par
    Caddy sur le réseau Docker : elle ne publie aucun port. Un client ne peut donc
    pas forger son adresse en nous parlant directement.
    """
    transmise = entetes.get("x-forwarded-for")
    if transmise:
        return transmise.split(",")[0].strip()
    return repli


class MiddlewareLimite:
    """Middleware ASGI qui refuse les requêtes au-delà de la limite.

    Écrit en ASGI brut et non avec `BaseHTTPMiddleware` : ce dernier enveloppe chaque
    requête dans une tâche et un flux anyio, ce qui coûte plus que le compteur
    lui-même. Un limiteur de débit est traversé par **toutes** les requêtes, y
    compris celles qu'il laisse passer.

    `/v1/sante` est exempté : la sonde de Docker l'interroge toutes les trente
    secondes, et une limite atteinte par ailleurs ne doit pas faire déclarer le
    conteneur malade — ce serait transformer un excès de trafic en panne.
    """

    EXEMPTS: Final = frozenset({"/v1/sante"})

    def __init__(self, app: ASGIApp, limiteur: Limiteur | None = None) -> None:
        self.app = app
        self.limiteur = limiteur if limiteur is not None else Limiteur(limite=limite_configuree())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.EXEMPTS:
            await self.app(scope, receive, send)
            return

        entetes = Headers(scope=scope)
        client = scope.get("client")
        repli = client[0] if client else "inconnu"
        if not entetes.get("x-forwarded-for") and repli in BOUCLE_LOCALE:
            await self.app(scope, receive, send)
            return

        adresse = adresse_cliente(entetes, repli)
        autorise, reessai = self.limiteur.autoriser(adresse)
        if autorise:
            await self.app(scope, receive, send)
            return

        journal.warning("limite atteinte par %s sur %s", adresse, scope.get("path"))
        reponse = JSONResponse(
            status_code=429,
            media_type="application/problem+json",
            headers={"Retry-After": str(reessai)},
            content={
                "type": "about:blank",
                "title": "Trop de requetes",
                "status": 429,
                "detail": (
                    f"Limite de {self.limiteur.limite} requetes par minute atteinte. "
                    f"Reessayez dans {reessai} seconde{'s' if reessai > 1 else ''}."
                ),
                "instance": str(scope.get("path", "")),
            },
        )
        await reponse(scope, receive, send)
