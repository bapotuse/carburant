-- 002 : tables raw et staging.
--
-- `raw.collecte` est la trace de chaque telechargement : elle permet de rejouer une
-- transformation sans retelecharger, et de savoir a quelle collecte remonte chaque
-- ligne de staging.
--
-- Le staging est le flux **aplati au format long**. Il est volontairement decoupe en
-- deux tables plutot qu'une seule : une ligne par station x carburant pour les prix,
-- et une ligne par station pour ses attributs. Tout mettre dans une table unique
-- repeterait l'adresse, les horaires et les services six fois par station, pour rien.

-- Ce fichier NE gere PAS sa transaction : c'est le lanceur de migrations qui
-- l'ouvre et la ferme (`carburant_etl.chargement.migrations`). Un `BEGIN`/`COMMIT`
-- ici ferait sauter la transaction externe au milieu de l'application.

-- ---------------------------------------------------------------- raw
CREATE TABLE IF NOT EXISTS raw.collecte (
    id           bigserial   PRIMARY KEY,
    source       text        NOT NULL,
    url          text        NOT NULL,
    debut        timestamptz NOT NULL,
    fin          timestamptz NOT NULL,
    octets       bigint      NOT NULL CHECK (octets >= 0),
    sha256       text        NOT NULL CHECK (length(sha256) = 64),
    -- NULL quand le contenu etait identique a la collecte precedente : aucun fichier
    -- n'a ete recree, mais la collecte a bien eu lieu.
    chemin       text,
    inchange     boolean     NOT NULL DEFAULT false,
    statut       text        NOT NULL DEFAULT 'en_cours'
                 CHECK (statut IN ('en_cours', 'succes', 'echec')),
    lignes       integer     CHECK (lignes IS NULL OR lignes >= 0),
    erreur       text,
    execution_id bigint      REFERENCES meta.execution_etl (id) ON DELETE SET NULL
);

COMMENT ON TABLE raw.collecte IS
  'Une ligne par telechargement. Permet de rejouer une transformation sans retelecharger.';
COMMENT ON COLUMN raw.collecte.chemin IS
  'Chemin du fichier brut compresse. NULL si le contenu etait identique a la collecte precedente.';
COMMENT ON COLUMN raw.collecte.sha256 IS
  'Empreinte du contenu telecharge, avant compression. Sert a detecter un contenu inchange.';

CREATE INDEX IF NOT EXISTS collecte_debut_idx ON raw.collecte (debut DESC);
CREATE INDEX IF NOT EXISTS collecte_succes_idx
    ON raw.collecte (source, debut DESC) WHERE statut = 'succes';

-- ---------------------------------------------------------------- staging
-- Attributs de station, une ligne par station et par collecte.
CREATE TABLE IF NOT EXISTS staging.station (
    collecte_id      bigint NOT NULL REFERENCES raw.collecte (id) ON DELETE CASCADE,
    station_id       bigint NOT NULL,
    -- Coordonnees issues du champ `geom` du flux, en degres decimaux. Les champs
    -- `latitude` et `longitude` du flux sont du texte en degres x 100 000 et ne sont
    -- jamais utilises (docs/reconnaissance.md section 1.3).
    longitude        double precision NOT NULL,
    latitude         double precision NOT NULL,
    cp               text,
    adresse          text,
    ville            text,
    -- 'R' route ou 'A' autoroute : les deux seules valeurs du flux.
    pop              text   CHECK (pop IN ('R', 'A')),
    departement      text,
    code_departement text,
    region           text,
    code_region      text,
    horaires         jsonb,
    services         text[],
    PRIMARY KEY (collecte_id, station_id)
);

COMMENT ON TABLE staging.station IS
  'Attributs de station, une ligne par station et par collecte. Alimente marts.dim_station.';

-- Prix, une ligne par station x carburant et par collecte : le format long.
CREATE TABLE IF NOT EXISTS staging.prix (
    collecte_id   bigint       NOT NULL REFERENCES raw.collecte (id) ON DELETE CASCADE,
    station_id    bigint       NOT NULL,
    carburant     text         NOT NULL
                  CHECK (carburant IN ('gazole', 'sp95', 'e10', 'sp98', 'e85', 'gplc')),
    prix          numeric(5,3),
    -- Instant du dernier CHANGEMENT de prix, pas du dernier controle. Lu en heure
    -- locale de Paris malgre le suffixe +00:00 de la source, puis stocke en UTC
    -- (docs/reconnaissance.md section 1.4).
    maj           timestamptz,
    rupture_type  text         CHECK (rupture_type IN ('temporaire', 'definitive')),
    rupture_debut timestamptz,
    PRIMARY KEY (collecte_id, station_id, carburant),
    -- Une ligne sans prix ET sans rupture n'apporte rien : on ne la charge pas.
    CONSTRAINT prix_ou_rupture CHECK (prix IS NOT NULL OR rupture_type IS NOT NULL),
    -- Un prix sans date de mise a jour serait inaffichable : la spec interdit
    -- d'afficher un prix nu.
    CONSTRAINT prix_avec_maj CHECK (prix IS NULL OR maj IS NOT NULL)
);

COMMENT ON TABLE staging.prix IS
  'Flux aplati au format long : une ligne par station x carburant et par collecte.';

CREATE INDEX IF NOT EXISTS prix_collecte_idx ON staging.prix (collecte_id);

-- ---------------------------------------------------------------- qualite
-- Comptage des rejets de validation, par collecte, par champ et par motif. C'est ce
-- qui rend visible une source qui derive, au lieu de la laisser echouer en silence.
CREATE TABLE IF NOT EXISTS staging.rejet (
    collecte_id bigint  NOT NULL REFERENCES raw.collecte (id) ON DELETE CASCADE,
    champ       text    NOT NULL,
    motif       text    NOT NULL,
    occurrences integer NOT NULL CHECK (occurrences > 0),
    -- Un exemple suffit a diagnostiquer ; en garder mille ne sert a rien.
    exemple     text,
    PRIMARY KEY (collecte_id, champ, motif)
);

COMMENT ON TABLE staging.rejet IS
  'Rejets de validation comptes par champ et par motif, avec un exemple. Une source qui derive se voit ici.';
