"""Le client de l'API publique. C'est la seule porte de sortie de ce paquet.

Le serveur MCP n'ouvre jamais la base de données : il appelle l'API, comme n'importe
quel visiteur du site. C'est ce qui permet à quiconque d'installer ce paquet sans
rien héberger, et c'est aussi ce qui garantit qu'un assistant voit exactement les
mêmes chiffres que le site.

**Les erreurs sont traduites pour un lecteur qui est un modèle de langage.** « HTTP
422 » ne lui apprend rien ; « le carburant "kerosene" n'existe pas, voici les six
valeurs acceptées » lui permet de reformuler sa question tout seul. L'API répond déjà
en `application/problem+json` avec un `detail` écrit dans cet esprit : on le relaie
plutôt que de le remplacer par un message maison.
"""

from __future__ import annotations

import os
from typing import Any, Final

import httpx

API_PAR_DEFAUT: Final = "https://carburant.144-24-195-97.sslip.io/v1"
"""Production par défaut : `uvx prix-carburant-mcp` doit marcher sans configuration.

Un recruteur qui essaie le paquet ne lira pas un README pour trouver une variable
d'environnement. L'URL reste surchargeable par `CARBURANT_API_BASE`, pour pointer sur
une instance locale pendant le développement.
"""

DELAI: Final = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)
"""Court à dessein. Un assistant qui attend trente secondes a déjà perdu la
conversation ; mieux vaut dire franchement que le service ne répond pas."""

VERSION_CLIENT: Final = "prix-carburant-mcp"


class ErreurAPI(RuntimeError):
    """Une erreur à relayer telle quelle à l'assistant.

    Le message est rédigé pour être lu par un modèle : il dit ce qui s'est passé
    **et** ce qui peut être tenté ensuite.
    """


def base_api() -> str:
    """URL de base de l'API, configurable par variable d'environnement."""
    return os.environ.get("CARBURANT_API_BASE", API_PAR_DEFAUT).rstrip("/")


def _detail(reponse: httpx.Response) -> str:
    """Le `detail` du problem+json, ou un repli lisible.

    On ne suppose pas que le corps est du JSON : une erreur peut venir du proxy
    inverse, qui renvoie du HTML, et planter ici transformerait une panne lisible en
    trace d'exception.
    """
    try:
        corps = reponse.json()
    except ValueError:
        return reponse.text.strip()[:200] or f"reponse vide, code {reponse.status_code}"
    if isinstance(corps, dict):
        detail = corps.get("detail") or corps.get("title")
        if isinstance(detail, str) and detail:
            return detail
    return f"code {reponse.status_code}"


def _traduire(reponse: httpx.Response) -> ErreurAPI:
    """Transforme une réponse d'erreur en message exploitable."""
    detail = _detail(reponse)
    code = reponse.status_code
    if code == 404:
        return ErreurAPI(f"Introuvable : {detail}")
    if code == 422:
        return ErreurAPI(f"Demande invalide : {detail}")
    if code == 429:
        attente = reponse.headers.get("Retry-After", "quelques")
        return ErreurAPI(
            f"L'API refuse temporairement les requetes, trop nombreuses. Attends "
            f"{attente} secondes avant de reessayer. ({detail})"
        )
    if code == 503:
        return ErreurAPI(
            f"Le service repond mais ne peut pas servir cette donnee pour l'instant : "
            f"{detail} Ne remplace pas ce chiffre par une estimation."
        )
    if code >= 500:
        return ErreurAPI(f"L'API est en panne (code {code}) : {detail}")
    return ErreurAPI(f"L'API a refuse la demande (code {code}) : {detail}")


class ClientCarburant:
    """Un client HTTP partagé pour toute la durée de vie du serveur.

    Un client par appel d'outil paierait une poignée de main TLS à chaque question,
    ce qui coûte plus cher que la requête elle-même.
    """

    def __init__(self, base: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.base = (base or base_api()).rstrip("/")
        self._client = client
        self._nous_avons_cree_le_client = client is None

    async def __aenter__(self) -> ClientCarburant:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DELAI,
                follow_redirects=True,
                headers={"User-Agent": VERSION_CLIENT, "Accept": "application/json"},
            )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None and self._nous_avons_cree_le_client:
            await self._client.aclose()
            self._client = None

    async def obtenir(self, chemin: str, **params: Any) -> dict[str, Any]:
        """Un GET sur l'API, qui rend le JSON ou lève une `ErreurAPI` lisible."""
        if self._client is None:  # pragma: no cover - mauvais usage
            raise RuntimeError("client non ouvert : utiliser `async with ClientCarburant()`")
        # Les paramètres absents sont retirés ici plutôt que chez chaque appelant :
        # `rayon_km=None` doit laisser l'API appliquer son défaut, pas lui envoyer
        # la chaîne « None ».
        propres = {cle: valeur for cle, valeur in params.items() if valeur is not None}
        url = f"{self.base}{chemin}"
        try:
            reponse = await self._client.get(url, params=propres)
        except httpx.TimeoutException:
            raise ErreurAPI(
                f"L'API n'a pas repondu a temps ({self.base}). Reessaie, ou dis que "
                "le service est momentanement indisponible."
            ) from None
        except httpx.HTTPError as erreur:
            raise ErreurAPI(
                f"L'API est injoignable ({self.base}) : {erreur}. Verifie "
                "CARBURANT_API_BASE si tu pointes sur une instance locale."
            ) from None

        if reponse.status_code >= 400:
            raise _traduire(reponse)
        try:
            corps = reponse.json()
        except ValueError:
            raise ErreurAPI("L'API a repondu autre chose que du JSON.") from None
        if not isinstance(corps, dict):
            raise ErreurAPI("L'API a repondu un JSON inattendu.")
        return corps
