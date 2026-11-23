-- 001 : schemas, extensions et table de suivi des executions.
--
-- Les quatre schemas du modele en couches :
--   raw      : trace des collectes, pour rejouer une transformation sans retelecharger
--   staging  : flux aplati au format long, une ligne par station x carburant
--   marts    : modele d'exposition (dimensions, faits, snapshots, vues)
--   meta     : journal des executions, source de la fraicheur affichee et des alertes

BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS meta;

COMMENT ON SCHEMA raw IS
  'Trace des collectes. Permet de rejouer une transformation sans retelecharger.';
COMMENT ON SCHEMA staging IS
  'Flux aplati au format long, une ligne par station x carburant. Charge par COPY.';
COMMENT ON SCHEMA marts IS
  'Modele d''exposition : dimensions, faits, snapshots et vues agregees.';
COMMENT ON SCHEMA meta IS
  'Journal des executions de l''ETL. Source de la fraicheur affichee et des alertes.';

-- Table des migrations appliquees. Pas d'outil tiers : des fichiers SQL numerotes et
-- une table de suivi suffisent, se lisent sans documentation, et s'expliquent en
-- entretien (voir docs/decisions.md).
CREATE TABLE IF NOT EXISTS meta.migration (
    nom         text        PRIMARY KEY,
    applique_le timestamptz NOT NULL DEFAULT now(),
    sha256      text        NOT NULL
);

COMMENT ON TABLE meta.migration IS
  'Migrations deja appliquees, avec le sha256 du fichier pour detecter une modification apres coup.';

-- Journal des executions. Alimente /v1/sante, /v1/meta et le dead man''s switch.
CREATE TABLE IF NOT EXISTS meta.execution_etl (
    id              bigserial   PRIMARY KEY,
    commande        text        NOT NULL,
    debut           timestamptz NOT NULL DEFAULT now(),
    fin             timestamptz,
    statut          text        NOT NULL DEFAULT 'en_cours'
                    CHECK (statut IN ('en_cours', 'succes', 'echec')),
    lignes_par_etape jsonb      NOT NULL DEFAULT '{}'::jsonb,
    avertissements  jsonb       NOT NULL DEFAULT '[]'::jsonb,
    erreur          text
);

COMMENT ON COLUMN meta.execution_etl.lignes_par_etape IS
  'Comptes par etape : extract, transform, load, qualite. Permet de voir ou une execution a maigri.';

CREATE INDEX IF NOT EXISTS execution_etl_debut_idx
    ON meta.execution_etl (debut DESC);
CREATE INDEX IF NOT EXISTS execution_etl_succes_idx
    ON meta.execution_etl (debut DESC) WHERE statut = 'succes';

COMMIT;
