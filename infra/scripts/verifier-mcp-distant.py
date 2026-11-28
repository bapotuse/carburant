"""Essai de bout en bout du connecteur MCP distant, avec un vrai client.

Ce que ce script verifie, et qu'aucun test en memoire ne peut verifier : que le
transport Streamable HTTP survit a Caddy, a TLS, a la validation de l'en-tete `Host`
et au mode sans etat. Chacun de ces quatre points a sa facon de tomber en silence --
une mise en tampon qui retient les evenements, un `Host` refuse avec un simple
avertissement dans les journaux.

Le dernier appel pose **la question du cadrage du projet** : « Je suis au Prado a
Marseille, ou est l'essence la moins chere ? ». Elle doit obtenir une demande de
precision, parce que l'avenue du Prado existe en 13006 et en 13008 : c'est le
comportement voulu, pas un echec.

    python infra/scripts/verifier-mcp-distant.py https://exemple.test/mcp
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from mcp.client.streamable_http import streamable_http_client

from mcp import ClientSession

OUTILS_ATTENDUS = {
    "comparer_carburants",
    "empreinte_carbone_plein",
    "meilleure_station_avec_autonomie",
    "prix_station",
    "tendance_prix",
    "trouver_station_moins_chere",
}


def _texte(resultat: Any) -> str:
    return "\n".join(
        bloc.text for bloc in resultat.content if getattr(bloc, "type", None) == "text"
    )


async def verifier(url: str) -> int:
    echecs: list[str] = []

    async with (
        streamable_http_client(url) as (lire, ecrire),
        ClientSession(lire, ecrire) as session,
    ):
        initialisation = await session.initialize()
        serveur = initialisation.server_info
        print(f"serveur : {serveur.name} v{serveur.version}")
        print(f"protocole : {initialisation.protocol_version}")
        if not (initialisation.instructions or "").strip():
            echecs.append("le serveur ne transmet pas ses instructions")

        noms = {outil.name for outil in (await session.list_tools()).tools}
        print(f"outils : {len(noms)}")
        if noms != OUTILS_ATTENDUS:
            echecs.append(f"outils inattendus : {sorted(noms ^ OUTILS_ATTENDUS)}")

        # 1. Une recherche qui doit aboutir, avec une adresse sans ambiguite.
        resultat = await session.call_tool(
            "trouver_station_moins_chere",
            {"lieu": "40 avenue du Prado, 13006 Marseille", "carburant": "diesel"},
        )
        print("\n--- trouver_station_moins_chere (adresse precise)")
        print(_texte(resultat)[:600])
        if resultat.is_error:
            echecs.append("la recherche a echoue sur une adresse precise")
        else:
            structure = resultat.structured_content or {}
            stations = structure.get("stations") or []
            if not stations:
                echecs.append("aucune station rendue autour du Prado")
            elif not stations[0].get("maj_affichee"):
                echecs.append("un prix est rendu sans sa date")

        # 2. L'empreinte, qui doit sortir avec sa source complete.
        resultat = await session.call_tool(
            "empreinte_carbone_plein", {"carburant": "gazole", "litres": 50}
        )
        print("\n--- empreinte_carbone_plein")
        print(_texte(resultat)[:400])
        if resultat.is_error:
            echecs.append("l'empreinte a echoue : les facteurs ADEME sont-ils charges ?")
        elif "ADEME" not in _texte(resultat):
            echecs.append("l'empreinte ne cite pas sa source")

        # 3. La question du cadrage. Une demande de precision est le bon resultat.
        resultat = await session.call_tool(
            "trouver_station_moins_chere",
            {"lieu": "le Prado, Marseille", "carburant": "gazole"},
        )
        print("\n--- trouver_station_moins_chere (« le Prado », ambigu)")
        print(_texte(resultat)[:500])
        if not resultat.is_error:
            echecs.append("« le Prado, Marseille » a ete tranche sans demander de precision")
        elif "13006" not in _texte(resultat):
            echecs.append("le refus ne nomme pas les candidats")

    if echecs:
        print("\nECHECS :", file=sys.stderr)
        for echec in echecs:
            print(f"  - {echec}", file=sys.stderr)
        return 1
    print("\nLe connecteur MCP distant repond correctement.")
    return 0


def principal() -> int:
    if len(sys.argv) != 2:
        print(f"usage : {sys.argv[0]} <url du connecteur>", file=sys.stderr)
        return 2
    return asyncio.run(verifier(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(principal())
