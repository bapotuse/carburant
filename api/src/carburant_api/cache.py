"""En-tetes de cache : `Cache-Control` et `ETag`.

Deux raisons de s'en occuper serieusement, et aucune n'est la performance brute :

- un prix qui change toutes les 15 minutes n'a aucune raison d'etre retelecharge a
  chaque fois qu'on revient sur la page, surtout depuis un telephone en 4G ;
- un `ETag` permet au navigateur de poser une question courte (« est-ce que ca a
  change ? ») et de recevoir une reponse de 0 octet.

L'`ETag` est calcule sur le corps serialise. C'est un `ETag` **faible** : deux
reponses identiques au champ `derniere_collecte` pres restent equivalentes du point
de vue de l'utilisateur, mais on ne cherche pas a le prouver -- on prefere une
comparaison exacte, simple a expliquer et impossible a prendre en defaut.
"""

from __future__ import annotations

import hashlib

from fastapi import Response
from pydantic import BaseModel


def calculer_etag(corps: BaseModel) -> str:
    """Empreinte stable du corps de la reponse."""
    serialise = corps.model_dump_json(exclude_none=False).encode("utf-8")
    return hashlib.sha256(serialise).hexdigest()[:32]


def poser_entetes(reponse: Response, corps: BaseModel, *, max_age: int) -> str:
    """Pose `Cache-Control` et `ETag` sur la reponse, et renvoie l'ETag.

    `stale-while-revalidate` laisse le navigateur afficher la version en cache
    pendant qu'il en demande une fraiche : sur un telephone, l'ecran se remplit tout
    de suite au lieu d'attendre le reseau.
    """
    etag = calculer_etag(corps)
    reponse.headers["ETag"] = f'"{etag}"'
    reponse.headers["Cache-Control"] = (
        f"public, max-age={max_age}, stale-while-revalidate={max_age // 2}"
    )
    return etag
