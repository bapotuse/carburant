#!/usr/bin/env bash
# `make deploy` : declenche le deploiement et attend son resultat.
#
# Le deploiement ne part pas d'ici. La session de developpement tourne dans un
# conteneur dont la sortie reseau passe par un proxy HTTPS : ssh, qui est du TCP
# brut sur le port 22, y est refuse. C'est une limite de l'environnement, pas une
# question de configuration du VPS (constate le 23/11/2026, voir docs/specs/infra.md).
#
# C'est donc un runner GitHub qui ouvre la connexion ssh, avec une cle rangee dans
# les secrets du depot. Ce script ne fait que demander au runner de s'y mettre.
set -euo pipefail

WORKFLOW=deploiement.yml
BRANCHE="${BRANCHE:-main}"

if ! command -v gh >/dev/null; then
    echo "Il faut la commande gh (GitHub CLI) pour declencher le deploiement." >&2
    exit 1
fi

echo "Verification que tout est pousse..."
if [ -n "$(git status --porcelain)" ]; then
    echo "Attention : des modifications ne sont pas commitees. Le deploiement" >&2
    echo "livrera ce qui est sur $BRANCHE, pas ce qui est sur le disque." >&2
fi
if ! git diff --quiet "origin/$BRANCHE" "$BRANCHE" 2>/dev/null; then
    echo "Attention : $BRANCHE locale et origin/$BRANCHE different." >&2
fi

echo "Declenchement du workflow $WORKFLOW sur $BRANCHE..."
gh workflow run "$WORKFLOW" --ref "$BRANCHE"

# `gh workflow run` ne renvoie pas l'identifiant de l'execution : on attend qu'elle
# apparaisse, puis on la suit. Sans cette attente, `gh run watch` suivrait la
# precedente.
echo "Attente du demarrage..."
for _ in $(seq 1 30); do
    sleep 2
    execution=$(gh run list --workflow "$WORKFLOW" --branch "$BRANCHE" \
        --event workflow_dispatch --limit 1 --json databaseId,status \
        --jq 'select(.[0].status != "completed") | .[0].databaseId' 2>/dev/null || true)
    [ -n "$execution" ] && break
done

if [ -z "${execution:-}" ]; then
    echo "L'execution n'est pas apparue. A regarder :" >&2
    echo "  gh run list --workflow $WORKFLOW" >&2
    exit 1
fi

gh run watch "$execution" --exit-status
echo "Deploiement termine. Journal complet : gh run view $execution --log"
