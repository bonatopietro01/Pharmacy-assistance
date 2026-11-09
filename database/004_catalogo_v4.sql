-- Sales Agents catalog schema v3 -> v4.
-- Apply through backend.catalog_setup so the user_version is checked first.
-- Existing demo values are retained; real products can keep price and stock unknown.
PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

CREATE TABLE fonti (
    id TEXT PRIMARY KEY NOT NULL,
    url TEXT UNIQUE,
    titolo TEXT NOT NULL CHECK(length(trim(titolo)) > 0),
    ente TEXT NOT NULL CHECK(length(trim(ente)) > 0),
    consultata_il TEXT NOT NULL,
    data_o_versione TEXT,
    tipo TEXT NOT NULL CHECK(tipo IN ('aifa','ministero','produttore','commerciale','farmacia','demo','altro'))
) STRICT;

INSERT INTO fonti (id, url, titolo, ente, consultata_il, data_o_versione, tipo)
VALUES ('SRC-DEMO-CATALOGO', NULL, 'Catalogo dimostrativo v3', 'Sales Agents', date('now'), 'schema v3', 'demo');

CREATE TABLE prodotti_v4 (
    codice TEXT PRIMARY KEY NOT NULL,
    nome TEXT NOT NULL CHECK(length(trim(nome)) > 0),
    categoria TEXT NOT NULL,
    formato TEXT NOT NULL,
    prezzo_cent INTEGER CHECK(prezzo_cent IS NULL OR prezzo_cent >= 0),
    quantita INTEGER CHECK(quantita IS NULL OR quantita >= 0),
    principio_attivo TEXT,
    dosaggio TEXT,
    via TEXT,
    immagine TEXT,
    fonte TEXT NOT NULL DEFAULT 'Catalogo dimostrativo',
    dataset_tipo TEXT NOT NULL DEFAULT 'demo' CHECK(dataset_tipo IN ('demo','reale')),
    stato_regolatorio TEXT NOT NULL DEFAULT 'non_verificato'
        CHECK(stato_regolatorio IN ('autorizzato','notificato','non_verificato','non_applicabile','sospeso','revocato')),
    stato_mercato TEXT NOT NULL DEFAULT 'non_verificato'
        CHECK(stato_mercato IN ('verificato','non_verificato','dimostrativo','cessato')),
    stato_revisione TEXT NOT NULL DEFAULT 'da_revisionare'
        CHECK(stato_revisione IN ('documentata','da_revisionare','approvata','respinta','dimostrativa')),
    tipo_id_regolatorio TEXT,
    id_regolatorio TEXT,
    prezzo_riferimento_cent INTEGER CHECK(prezzo_riferimento_cent IS NULL OR prezzo_riferimento_cent >= 0),
    prezzo_riferimento_fonte_id TEXT REFERENCES fonti(id),
    prezzo_riferimento_data TEXT,
    prezzo_banco_fonte_id TEXT REFERENCES fonti(id),
    prezzo_banco_data TEXT,
    quantita_fonte_id TEXT REFERENCES fonti(id),
    quantita_data TEXT,
    immagine_fonte_id TEXT REFERENCES fonti(id),
    CHECK(prezzo_cent IS NULL OR prezzo_banco_fonte_id IS NOT NULL),
    CHECK(quantita IS NULL OR quantita_fonte_id IS NOT NULL),
    CHECK(prezzo_riferimento_cent IS NULL OR prezzo_riferimento_fonte_id IS NOT NULL),
    CHECK(dataset_tipo != 'reale' OR stato_mercato != 'dimostrativo')
) STRICT;

INSERT INTO prodotti_v4 (
    codice, nome, categoria, formato, prezzo_cent, quantita, principio_attivo, dosaggio, via, immagine, fonte,
    dataset_tipo, stato_regolatorio, stato_mercato, stato_revisione,
    prezzo_banco_fonte_id, prezzo_banco_data, quantita_fonte_id, quantita_data
)
SELECT codice, nome, categoria, formato, prezzo_cent, quantita, principio_attivo, dosaggio, via, immagine, fonte,
       'demo', 'non_applicabile', 'dimostrativo', 'dimostrativa',
       'SRC-DEMO-CATALOGO', date('now'), 'SRC-DEMO-CATALOGO', date('now')
FROM prodotti;

DROP TABLE prodotti;
ALTER TABLE prodotti_v4 RENAME TO prodotti;

CREATE TABLE principi_attivi (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL CHECK(length(trim(nome)) > 0),
    nome_normalizzato TEXT NOT NULL UNIQUE CHECK(length(trim(nome_normalizzato)) > 0)
) STRICT;

CREATE TABLE prodotto_principi_attivi (
    prodotto_codice TEXT NOT NULL REFERENCES prodotti(codice) ON DELETE CASCADE,
    principio_attivo_id INTEGER NOT NULL REFERENCES principi_attivi(id),
    quantita_per_unita TEXT,
    unita TEXT,
    fonte_id TEXT REFERENCES fonti(id),
    PRIMARY KEY (prodotto_codice, principio_attivo_id),
    CHECK(quantita_per_unita IS NULL OR length(trim(quantita_per_unita)) > 0),
    CHECK(unita IS NULL OR length(trim(unita)) > 0)
) STRICT;

INSERT INTO principi_attivi (nome, nome_normalizzato)
SELECT DISTINCT trim(principio_attivo), lower(trim(principio_attivo))
FROM prodotti WHERE principio_attivo IS NOT NULL AND length(trim(principio_attivo)) > 0;

INSERT INTO prodotto_principi_attivi (prodotto_codice, principio_attivo_id, fonte_id)
SELECT p.codice, a.id, 'SRC-DEMO-CATALOGO'
FROM prodotti p JOIN principi_attivi a ON a.nome_normalizzato = lower(trim(p.principio_attivo))
WHERE p.principio_attivo IS NOT NULL AND length(trim(p.principio_attivo)) > 0;

CREATE TABLE componenti_integratore (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL CHECK(length(trim(nome)) > 0),
    nome_normalizzato TEXT NOT NULL UNIQUE CHECK(length(trim(nome_normalizzato)) > 0),
    tipo TEXT NOT NULL CHECK(tipo IN ('vitamina','minerale','estratto','probiotico','altro'))
) STRICT;

CREATE TABLE prodotto_componenti_integratore (
    prodotto_codice TEXT NOT NULL REFERENCES prodotti(codice) ON DELETE CASCADE,
    componente_id INTEGER NOT NULL REFERENCES componenti_integratore(id),
    quantita_per_unita TEXT,
    unita TEXT,
    fonte_id TEXT REFERENCES fonti(id),
    PRIMARY KEY (prodotto_codice, componente_id),
    CHECK(quantita_per_unita IS NULL OR length(trim(quantita_per_unita)) > 0),
    CHECK(unita IS NULL OR length(trim(unita)) > 0)
) STRICT;

CREATE TABLE alias_prodotto (
    prodotto_codice TEXT NOT NULL REFERENCES prodotti(codice) ON DELETE CASCADE,
    alias TEXT NOT NULL CHECK(length(trim(alias)) > 0),
    tipo TEXT NOT NULL CHECK(tipo IN ('nome_commerciale','sinonimo','nome_uso_comune','codice_pubblico')),
    fonte_id TEXT REFERENCES fonti(id),
    PRIMARY KEY (prodotto_codice, alias, tipo)
) STRICT;

CREATE TABLE prodotto_fonti (
    prodotto_codice TEXT NOT NULL REFERENCES prodotti(codice) ON DELETE CASCADE,
    fonte_id TEXT NOT NULL REFERENCES fonti(id),
    affermazione TEXT NOT NULL CHECK(affermazione IN
        ('identita','composizione','stato_regolatorio','commercializzazione','immagine','prezzo_riferimento','prezzo_banco','scorte','equivalenza','associazione_clinica','identificativo_regolatorio','dato_storico')),
    stato_verifica TEXT NOT NULL CHECK(stato_verifica IN ('verificata','candidata','respinta','demo')),
    PRIMARY KEY (prodotto_codice, fonte_id, affermazione)
) STRICT;

INSERT INTO prodotto_fonti (prodotto_codice, fonte_id, affermazione, stato_verifica)
SELECT codice, 'SRC-DEMO-CATALOGO', 'identita', 'demo' FROM prodotti;
INSERT INTO prodotto_fonti (prodotto_codice, fonte_id, affermazione, stato_verifica)
SELECT codice, 'SRC-DEMO-CATALOGO', 'prezzo_banco', 'demo' FROM prodotti;
INSERT INTO prodotto_fonti (prodotto_codice, fonte_id, affermazione, stato_verifica)
SELECT codice, 'SRC-DEMO-CATALOGO', 'scorte', 'demo' FROM prodotti;

CREATE TABLE relazioni_prodotti_v4 (
    origine TEXT NOT NULL REFERENCES prodotti(codice) ON DELETE CASCADE,
    destinazione TEXT NOT NULL REFERENCES prodotti(codice) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK(tipo IN
        ('equivalente_demo','equivalente_documentato','complemento_cosmetico','complemento_revisionato','complemento_clinico')),
    fonte TEXT NOT NULL,
    condizioni TEXT NOT NULL,
    motivo TEXT NOT NULL DEFAULT '',
    esclusioni TEXT,
    revisore TEXT,
    stato_revisione TEXT NOT NULL DEFAULT 'candidata'
        CHECK(stato_revisione IN ('demo','candidata','approvata','respinta')),
    fonte_id TEXT REFERENCES fonti(id),
    versione_fonte TEXT,
    benefici TEXT,
    rischi TEXT,
    prerequisiti TEXT,
    revisionato_il TEXT,
    PRIMARY KEY (origine, destinazione, tipo),
    CHECK(origine != destinazione),
    CHECK(stato_revisione != 'approvata' OR (fonte_id IS NOT NULL AND revisore IS NOT NULL
        AND length(trim(revisore)) > 0 AND revisionato_il IS NOT NULL)),
    CHECK(tipo != 'complemento_clinico' OR stato_revisione != 'approvata' OR
        (length(trim(condizioni)) > 0 AND length(trim(motivo)) > 0
         AND benefici IS NOT NULL AND length(trim(benefici)) > 0
         AND rischi IS NOT NULL AND length(trim(rischi)) > 0
         AND prerequisiti IS NOT NULL AND length(trim(prerequisiti)) > 0
         AND esclusioni IS NOT NULL AND length(trim(esclusioni)) > 0)),
    CHECK(tipo NOT IN ('equivalente_documentato','complemento_revisionato','complemento_clinico')
        OR stato_revisione IN ('demo','candidata','respinta')
        OR (revisore IS NOT NULL AND length(trim(revisore)) > 0)),
    CHECK(tipo != 'complemento_revisionato' OR (esclusioni IS NOT NULL AND length(trim(esclusioni)) > 0))
) STRICT;

INSERT INTO relazioni_prodotti_v4 (
    origine, destinazione, tipo, fonte, condizioni, esclusioni, revisore, stato_revisione, fonte_id, versione_fonte
)
SELECT origine, destinazione, tipo, fonte, condizioni, esclusioni, revisore, 'demo', 'SRC-DEMO-CATALOGO', 'schema v3 demo'
FROM relazioni_prodotti;

DROP TABLE relazioni_prodotti;
ALTER TABLE relazioni_prodotti_v4 RENAME TO relazioni_prodotti;

CREATE TABLE concetti (
    id TEXT PRIMARY KEY NOT NULL,
    nome TEXT NOT NULL CHECK(length(trim(nome)) > 0),
    tipo TEXT NOT NULL CHECK(tipo IN ('sintomo','condizione','tema','bisogno','servizio'))
) STRICT;

CREATE TABLE relazioni_concetto_prodotto (
    concetto_id TEXT NOT NULL REFERENCES concetti(id) ON DELETE CASCADE,
    prodotto_codice TEXT NOT NULL REFERENCES prodotti(codice) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK(tipo IN ('indicazione_etichetta','associazione_clinica','contesto_ricerca')),
    contesto TEXT NOT NULL DEFAULT '',
    benefici TEXT NOT NULL DEFAULT '',
    rischi TEXT NOT NULL DEFAULT '',
    prerequisiti TEXT NOT NULL DEFAULT '',
    esclusioni TEXT NOT NULL DEFAULT '',
    fonte_id TEXT REFERENCES fonti(id),
    versione_fonte TEXT,
    stato_revisione TEXT NOT NULL DEFAULT 'candidata'
        CHECK(stato_revisione IN ('candidata','approvata','respinta','demo')),
    revisore TEXT,
    revisionato_il TEXT,
    PRIMARY KEY (concetto_id, prodotto_codice, tipo),
    CHECK(stato_revisione != 'approvata' OR (fonte_id IS NOT NULL AND revisore IS NOT NULL
        AND length(trim(revisore)) > 0 AND revisionato_il IS NOT NULL
        AND length(trim(contesto)) > 0 AND length(trim(benefici)) > 0
        AND length(trim(rischi)) > 0 AND length(trim(prerequisiti)) > 0
        AND length(trim(esclusioni)) > 0))
) STRICT;

CREATE INDEX idx_prodotto_principi_attivi_ingrediente
    ON prodotto_principi_attivi(principio_attivo_id, prodotto_codice);
CREATE INDEX idx_prodotto_componenti_integratore
    ON prodotto_componenti_integratore(componente_id, prodotto_codice);
CREATE INDEX idx_alias_prodotto_lookup ON alias_prodotto(alias COLLATE NOCASE);
CREATE INDEX idx_prodotto_fonti_status ON prodotto_fonti(affermazione, stato_verifica);
CREATE INDEX idx_relazioni_prodotti_status ON relazioni_prodotti(origine, stato_revisione, tipo);
CREATE INDEX idx_relazioni_concetto_status ON relazioni_concetto_prodotto(concetto_id, stato_revisione);

PRAGMA user_version = 4;
COMMIT;
PRAGMA foreign_keys = ON;
