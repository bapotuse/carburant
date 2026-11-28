"""Serveur MCP : prix des carburants en France.

Deux transports, et deux usages distincts :

- **stdio**, pour une installation locale (`uvx prix-carburant-mcp`). Le client lance
  le processus et lui parle sur son entrée standard.
- **Streamable HTTP**, pour le connecteur distant déployé sur le VPS. Un recruteur
  l'ajoute à son client MCP sans rien installer.

Le serveur n'ouvre jamais la base de données : il appelle l'API publique, comme
n'importe quel visiteur du site. C'est ce qui permet de l'installer sans rien héberger,
et ce qui garantit qu'un assistant voit exactement les mêmes chiffres que le site.

**Le transport HTTP est sans état** (`stateless_http`). Le VPS n'a pas de mémoire
partagée entre requêtes, et une session MCP qui vivrait dans un seul processus
casserait au premier redémarrage. Sans état, chaque requête se suffit à elle-même.

**Les instructions du serveur comptent autant que les descriptions d'outils.** Elles
sont lues avant la première question et portent ce qu'aucun outil ne peut dire seul :
qu'un prix s'énonce toujours avec sa date, et qu'une adresse ambiguë se fait préciser
au lieu de se deviner.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from typing import Any, Final

from mcp.server.mcpserver import MCPServer

from carburant_mcp.client import API_PAR_DEFAUT, ClientCarburant, base_api
from carburant_mcp.outils import analyses, stations

journal = logging.getLogger("carburant.mcp")

NOM: Final = "carburant"
VERSION: Final = "0.1.0"

INSTRUCTIONS: Final = """\
Prix des carburants dans les quelque 9 800 stations-service de France metropolitaine
et de Corse, mis a jour toutes les quinze minutes depuis le flux officiel du
gouvernement. Six carburants : gazole, SP95, SP95-E10, SP98, superethanol E85, GPL.

Quatre regles pour repondre juste avec ces outils.

1. **Un prix ne s'enonce jamais sans sa date.** Chaque reponse porte l'age du prix
   (« il y a 2 heures »). Dis-le. « L'essence est a 1,75 EUR » devient faux en
   silence ; « 1,75 EUR, releve il y a deux heures » reste vrai.

2. **Une adresse ambigue se fait preciser, jamais deviner.** L'avenue du Prado existe
   en 13006 et en 13008, a un kilometre l'une de l'autre, sans aucune station en
   commun. Quand un outil refuse en listant des candidats, demande lequel.

3. **Avec une autonomie limitee, prends `meilleure_station_avec_autonomie`** et non la
   station la moins chere : y aller consomme du carburant, et la moins chere n'est pas
   toujours la moins chere. Les hypotheses du calcul sont dans la reponse ; cite-les si
   on te demande d'ou sort le chiffre.

4. **Les chiffres de CO2 viennent de la Base Carbone de l'ADEME** et sortent avec leur
   source complete. Cite-la. Si un facteur manque, l'outil refuse : n'estime pas a la
   place.

Ce que ces donnees ne contiennent pas : aucune station d'outre-mer, et pas de nom de
station dans le flux officiel — les enseignes viennent d'OpenStreetMap, qui en couvre
99,4 %. Une station sans enseigne connue s'identifie par son adresse.
"""


def creer_serveur(client: ClientCarburant) -> MCPServer[Any]:
    """Assemble le serveur et ses six outils.

    Le client est injecté plutôt que créé ici : les tests en mémoire en fournissent un
    qui parle à une API simulée, sans réseau.
    """
    serveur: MCPServer[Any] = MCPServer(
        name=NOM,
        title="Prix des carburants en France",
        instructions=INSTRUCTIONS,
        version=VERSION,
        website_url="https://github.com/bapotuse/carburant",
    )
    stations.enregistrer(serveur, client)
    analyses.enregistrer(serveur, client)
    return serveur


async def _servir(transport: str, hote: str, port: int) -> None:
    """Ouvre le client HTTP pour toute la durée de vie du serveur, puis sert."""
    async with ClientCarburant() as client:
        serveur = creer_serveur(client)
        if transport == "stdio":
            await serveur.run_stdio_async()
        else:
            # Sans etat : le VPS n'a pas de memoire partagee entre requetes, et une
            # session qui vivrait dans un seul processus casserait au redemarrage.
            await serveur.run_streamable_http_async(
                host=hote, port=port, streamable_http_path="/mcp", stateless_http=True
            )


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée de la commande `prix-carburant-mcp`."""
    parseur = argparse.ArgumentParser(
        prog="prix-carburant-mcp",
        description="Serveur MCP des prix des carburants en France.",
    )
    parseur.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio pour un client local, http pour le connecteur distant",
    )
    parseur.add_argument("--hote", default="127.0.0.1", help="adresse d'ecoute du transport http")
    parseur.add_argument("--port", type=int, default=8080, help="port d'ecoute du transport http")
    parseur.add_argument(
        "--verifier",
        action="store_true",
        help="assemble le serveur, liste ses outils et sort : sert au smoke test",
    )
    args = parseur.parse_args(argv)

    # Les journaux partent sur la sortie d'erreur : en stdio, la sortie standard est
    # le canal du protocole, et y ecrire une ligne de log casse la session.
    logging.basicConfig(
        level=os.environ.get("CARBURANT_MCP_LOG", "INFO"),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )

    if args.verifier:
        serveur = creer_serveur(ClientCarburant())
        noms = sorted(outil.name for outil in asyncio.run(serveur.list_tools()))
        # Sur la sortie standard et non dans le journal : c'est le **resultat** de
        # la commande, ce que le smoke test lit. Les journaux, eux, vont sur la
        # sortie d'erreur, parce qu'en stdio la sortie standard porte le protocole.
        sys.stdout.write(f"{len(noms)} outils : {', '.join(noms)}\n")
        sys.stdout.write(f"API : {base_api()}\n")
        return 0

    journal.info(
        "serveur MCP « %s » v%s, transport %s, API %s", NOM, VERSION, args.transport, base_api()
    )
    try:
        asyncio.run(_servir(args.transport, args.hote, args.port))
    except KeyboardInterrupt:  # pragma: no cover - interruption manuelle
        return 130
    return 0


__all__ = ["API_PAR_DEFAUT", "INSTRUCTIONS", "base_api", "creer_serveur", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
