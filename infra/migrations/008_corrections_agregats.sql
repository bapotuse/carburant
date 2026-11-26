-- 008 : deux commentaires qui promettaient plus que ce que le code fait.
--
-- Ce fichier NE gere PAS sa transaction : c'est le lanceur de migrations qui
-- l'ouvre et la ferme (`carburant_etl.chargement.migrations`).
--
-- L'audit independant du 26/11/2026 a releve que le commentaire de
-- `agregat_prix_jour.exclus` annoncait « atypiques, anciens, perimes ou en rupture »
-- alors que seuls les atypiques y sont comptes : les perimes et les ruptures sont
-- ecartes **avant** le calcul, par la fenetre de lecture et par le `NOT EXISTS`, et
-- n'atteignent jamais le compteur. Mesure : le 24/11/2026, 1 005 prix perimes
-- ecartes sans etre comptes.
--
-- Le choix reste le bon -- les compter demanderait de lire des prix dont on sait
-- deja qu'ils ne temoignent de rien -- mais il fallait le dire.

COMMENT ON COLUMN marts.agregat_prix_jour.exclus IS
  'Prix atypiques (marts.est_suspect) ecartes du calcul mais comptes. Les prix perimes et les carburants en rupture, eux, sont ecartes avant le calcul et ne sont pas comptes ici.';

COMMENT ON COLUMN marts.agregat_prix_jour.stations IS
  'Nombre de prix retenus dans le calcul. Sur les trente premiers jours d une periode amorcee, il est faible : la fenetre de peremption n est pas encore couverte par les donnees disponibles.';
