# Carburant -- commandes du projet.
#
# Toutes les cibles s'executent depuis la racine du depot. `make aide` liste tout.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := aide

COMPOSE := docker compose
UV := uv run
PNPM := cd web && pnpm

# Jalon courant : destination des captures. `make captures JALON=J1` pour en changer.
JALON ?= J0

.PHONY: aide up down logs migrate etl test check captures deploy \
        lint format typage test-python test-front openapi client-api purger captures-brutes

aide: ## Liste les commandes disponibles
	@grep -hE '^[a-z][a-zA-Z0-9_-]*:.*##' $(MAKEFILE_LIST) \
		| sed 's/:.*##/\t/' \
		| awk -F'\t' '{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------------- cycle de vie
up: ## Demarre la pile locale et applique les migrations
	@test -f .env || { echo "Pas de .env : cp .env.example .env puis completer." >&2; exit 1; }
	# La base d'abord, puis les migrations, puis le reste : sur une base vierge,
	# `/v1/sante` interroge `meta.execution_etl`, qui n'existe qu'une fois les
	# migrations passees. Tout demarrer d'un coup ferait echouer le healthcheck de
	# l'API sur une machine propre.
	$(COMPOSE) up -d --build --wait db
	$(MAKE) --no-print-directory migrate
	$(COMPOSE) up -d --build --wait
	@echo
	@echo "  API    http://localhost:$${API_PORT:-8000}/docs"
	@echo "  Site   http://localhost:$${WEB_PORT:-3000}"

down: ## Arrete la pile (les volumes sont conserves)
	$(COMPOSE) down

logs: ## Suit les journaux de tous les services
	$(COMPOSE) logs -f --tail=100

purger: ## Arrete la pile et efface les volumes -- DESTRUCTIF, demande confirmation
	@printf 'Effacer les volumes carburant_donnees_db et carburant_donnees_brutes ? [tapez oui] '
	@read -r reponse; test "$$reponse" = "oui" || { echo "Annule."; exit 1; }
	$(COMPOSE) down -v

migrate: ## Applique les migrations SQL non encore appliquees
	./infra/scripts/migrer.sh

# ----------------------------------------------------------------- ETL
etl: ## Lance une collecte complete (extract, transform, load, qualite)
	$(COMPOSE) run --rm etl etl run

# ----------------------------------------------------------------- qualite
check: lint format typage test ## Lint, formatage, typage et tests : la porte de sortie
	@echo "make check : tout est vert."

lint: ## Lint Python et front
	$(UV) ruff check .
	$(PNPM) lint

format: ## Verifie le formatage (ne modifie rien)
	$(UV) ruff format --check .
	$(PNPM) format:check

typage: ## Typage Python strict et front
	$(UV) mypy --strict etl api mcp
	$(PNPM) typecheck

test: test-python test-front ## Toute la suite de tests

test-python: ## Tests Python
	$(UV) pytest

test-front: ## Tests unitaires du front
	$(PNPM) test

captures: ## Produit les captures mobiles dans docs/captures/$(JALON)/
	$(PNPM) build
	JALON=$(JALON) $(MAKE) --no-print-directory captures-brutes
	$(UV) python infra/scripts/compresser_captures.py docs/captures/$(JALON)

captures-brutes:
	cd web && JALON=$(JALON) pnpm captures

# ----------------------------------------------------------------- contrat d'API
openapi: ## Ecrit le schema OpenAPI dans web/openapi.json
	$(UV) python -c "import json,sys; from carburant_api.app import app; \
		json.dump(app.openapi(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)" \
		> web/openapi.json
	@echo "web/openapi.json ecrit."

client-api: openapi ## Regenere le client TypeScript depuis l'OpenAPI
	$(PNPM) generer-client

# ----------------------------------------------------------------- deploiement
deploy: ## Deploie sur le VPS (images GHCR, migrations, smoke test)
	./infra/scripts/deployer.sh
