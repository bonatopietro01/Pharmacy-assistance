-- Schema v7.
--   1. alias_prodotto accetta il tipo 'errore_asr' (storpiature ricorrenti del
--      riconoscimento vocale) e uno stato di revisione: un alias proposto dal
--      feedback resta 'candidata' finché il farmacista non lo approva.
--   2. aggiunge ATC e stato di carenza ai prodotti e il registro degli import;
--   3. rimuove le tabelle `wiki` e `wiki_fts` del primo prototipo, non più lette
--      dal backend (la wiki è indicizzata in memoria da wiki/schede/*.md).
-- Si applica con: python backend/catalog_setup.py migrate-latest --catalog <copia>

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE alias_prodotto_v7 (
    prodotto_codice TEXT NOT NULL REFERENCES prodotti(codice) ON DELETE CASCADE,
    alias TEXT NOT NULL CHECK(length(trim(alias)) > 0),
    tipo TEXT NOT NULL CHECK(tipo IN ('nome_commerciale','sinonimo','nome_uso_comune','codice_pubblico','errore_asr')),
    fonte_id TEXT REFERENCES fonti(id),
    stato_revisione TEXT NOT NULL DEFAULT 'approvata' CHECK(stato_revisione IN ('candidata','approvata','respinta')),
    revisore TEXT,
    PRIMARY KEY (prodotto_codice, alias, tipo)
) STRICT;
INSERT INTO alias_prodotto_v7 (prodotto_codice, alias, tipo, fonte_id)
    SELECT prodotto_codice, alias, tipo, fonte_id FROM alias_prodotto;
DROP TABLE alias_prodotto;
ALTER TABLE alias_prodotto_v7 RENAME TO alias_prodotto;

-- 3. dati dall'anagrafica AIFA e dall'elenco dei farmaci carenti
ALTER TABLE prodotti ADD COLUMN atc TEXT;
ALTER TABLE prodotti ADD COLUMN carente INTEGER NOT NULL DEFAULT 0 CHECK(carente IN (0, 1));
ALTER TABLE prodotti ADD COLUMN carenza_aggiornata_il TEXT;

-- 4. esito degli import (AIFA, gestionale) per la pagina di diagnostica
CREATE TABLE IF NOT EXISTS registro_import (
    id INTEGER PRIMARY KEY,
    fonte TEXT NOT NULL,
    eseguito_il TEXT NOT NULL,
    esito TEXT NOT NULL CHECK(esito IN ('ok','parziale','errore')),
    righe_lette INTEGER NOT NULL DEFAULT 0,
    righe_applicate INTEGER NOT NULL DEFAULT 0,
    righe_rifiutate INTEGER NOT NULL DEFAULT 0,
    nota TEXT NOT NULL DEFAULT ''
) STRICT;

DROP TABLE IF EXISTS wiki_fts;
DROP TABLE IF EXISTS wiki;

PRAGMA user_version = 7;
COMMIT;
PRAGMA foreign_keys = ON;
