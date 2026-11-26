-- 007 : les facteurs d'emission de la Base Carbone de l'ADEME.
--
-- Ce fichier NE gere PAS sa transaction : c'est le lanceur de migrations qui
-- l'ouvre et la ferme (`carburant_etl.chargement.migrations`).
--
-- **Jamais de mise a jour en place.** Une nouvelle version de la Base Carbone
-- donne une nouvelle ligne, et les anciennes restent. Un chiffre d'empreinte
-- carbone publie sur le site doit rester explicable six mois plus tard : si l'ADEME
-- revise un facteur, on veut pouvoir dire quelle valeur etait affichee a quelle
-- date, et non decouvrir que le passe a change tout seul.
--
-- Chaque ligne porte sa provenance complete : identifiant de l'element, libelle
-- exact tel que l'ADEME l'ecrit, unite, perimetre, localisation, statut, date de
-- modification et periode de validite de l'element, version du jeu de donnees, URL
-- et date de recuperation. C'est ce qui permet d'afficher la source sous le chiffre.
--
-- Un meme element couvre parfois plusieurs carburants : l'element 25763
-- « Essence / Supercarburant sans plomb (95, 95-E10, 98) » vaut pour le SP95 et le
-- SP98. Le mapping est donc par carburant, pas par element.

CREATE TABLE IF NOT EXISTS marts.ref_facteur_emission (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    carburant         text NOT NULL REFERENCES marts.dim_carburant (code),
    element_ademe     text NOT NULL,
    nom_base          text NOT NULL,
    nom_attribut      text,
    valeur            numeric(8,4) NOT NULL CHECK (valeur > 0),
    unite             text NOT NULL,
    localisation      text,
    statut            text,
    date_modification text,
    periode_validite  text,
    -- `updatedAt` du jeu de donnees : la Base Carbone n'expose pas de numero de
    -- version, c'est le seul reperage dont on dispose.
    version_base      text NOT NULL,
    url               text NOT NULL,
    recupere_le       timestamptz NOT NULL DEFAULT now(),
    -- Une seule ligne par carburant et par version du jeu : relancer la
    -- recuperation ne cree pas de doublon, mais une nouvelle version en cree bien
    -- une nouvelle.
    UNIQUE (carburant, version_base, element_ademe)
);

COMMENT ON TABLE marts.ref_facteur_emission IS
  'Facteurs d emission par litre, Base Carbone ADEME. Historise : une nouvelle version donne une nouvelle ligne, jamais une mise a jour en place.';
COMMENT ON COLUMN marts.ref_facteur_emission.version_base IS
  'updatedAt du jeu de donnees ADEME. La Base Carbone n expose pas de numero de version.';
COMMENT ON COLUMN marts.ref_facteur_emission.nom_base IS
  'Libelle exact tel que l ADEME l ecrit. Recopie sans retouche : c est lui qui sera affiche comme source.';

CREATE INDEX IF NOT EXISTS ref_facteur_emission_carburant
    ON marts.ref_facteur_emission (carburant, recupere_le DESC);

-- Le facteur en vigueur pour chaque carburant : le plus recemment recupere.
CREATE OR REPLACE VIEW marts.facteur_emission_courant AS
SELECT DISTINCT ON (carburant)
       carburant, element_ademe, nom_base, nom_attribut, valeur, unite,
       localisation, statut, date_modification, periode_validite,
       version_base, url, recupere_le
  FROM marts.ref_facteur_emission
 ORDER BY carburant, recupere_le DESC, id DESC;

COMMENT ON VIEW marts.facteur_emission_courant IS
  'Le facteur d emission en vigueur pour chaque carburant : le plus recemment recupere.';
