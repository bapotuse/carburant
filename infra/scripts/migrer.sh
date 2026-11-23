#!/usr/bin/env bash
# Applique les migrations de infra/migrations/ qui ne le sont pas encore.
#
# Idempotent : relancer ne fait rien. Si un fichier deja applique a ete modifie, le
# script s'arrete en le disant plutot que de laisser deux bases diverger en silence.
set -euo pipefail

racine="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
repertoire="$racine/infra/migrations"
service="${SERVICE_DB:-db}"
utilisateur="${POSTGRES_USER:-carburant}"
base="${POSTGRES_DB:-carburant}"

psql_() {
    docker compose exec -T "$service" psql -v ON_ERROR_STOP=1 -U "$utilisateur" -d "$base" "$@"
}

if ! psql_ -tAc 'SELECT 1' > /dev/null 2>&1; then
    echo "La base n'est pas joignable. Lancer 'make up' d'abord." >&2
    exit 1
fi

# La toute premiere migration cree la table de suivi : on ne peut pas l'interroger avant.
deja_appliquees=""
if psql_ -tAc "SELECT to_regclass('meta.migration') IS NOT NULL" | grep -q '^t$'; then
    deja_appliquees="$(psql_ -tAc 'SELECT nom || '"'"' '"'"' || sha256 FROM meta.migration')"
fi

applique=0
for fichier in "$repertoire"/*.sql; do
    nom="$(basename "$fichier")"
    somme="$(sha256sum "$fichier" | cut -d' ' -f1)"

    if printf '%s\n' "$deja_appliquees" | grep -q "^$nom $somme\$"; then
        continue
    fi
    if printf '%s\n' "$deja_appliquees" | grep -q "^$nom "; then
        echo "ERREUR : $nom a deja ete appliquee mais son contenu a change." >&2
        echo "Ne jamais modifier une migration appliquee : en ajouter une nouvelle." >&2
        exit 1
    fi

    echo "-> $nom"
    psql_ -f - < "$fichier"
    psql_ -c "INSERT INTO meta.migration (nom, sha256) VALUES ('$nom', '$somme')"
    applique=$((applique + 1))
done

if [ "$applique" -eq 0 ]; then
    echo "Base a jour : aucune migration a appliquer."
else
    echo "$applique migration(s) appliquee(s)."
fi
