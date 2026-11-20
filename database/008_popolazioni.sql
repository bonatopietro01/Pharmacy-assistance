-- Schema v8: idoneità dei prodotti per popolazione (età, sesso, gravidanza, allattamento, specie).
-- Ogni riga ha una fonte; solo il farmacista la porta ad «approvata». Le righe «candidata»
-- producono etichette e ordinamento ma escludono solo se l'esito è «controindicato».
BEGIN;
CREATE TABLE IF NOT EXISTS prodotto_popolazione (
    id INTEGER PRIMARY KEY,
    prodotto_codice TEXT NOT NULL REFERENCES prodotti(codice) ON DELETE CASCADE,
    popolazione TEXT NOT NULL CHECK(popolazione IN ('neonato','bambino','adolescente','adulto','anziano','donna',
                                                    'uomo','gravidanza','allattamento','cane','gatto')),
    eta_min_mesi INTEGER CHECK(eta_min_mesi IS NULL OR eta_min_mesi BETWEEN 0 AND 1500),
    eta_max_mesi INTEGER CHECK(eta_max_mesi IS NULL OR eta_max_mesi BETWEEN 0 AND 1500),
    esito TEXT NOT NULL CHECK(esito IN ('indicato','formulazione_dedicata','cautela','sconsigliato','controindicato')),
    nota TEXT NOT NULL DEFAULT '',
    fonte_id TEXT NOT NULL REFERENCES fonti(id),
    stato_revisione TEXT NOT NULL DEFAULT 'candidata' CHECK(stato_revisione IN ('candidata','approvata','respinta')),
    revisore TEXT,
    revisionato_il TEXT,
    UNIQUE (prodotto_codice, popolazione, eta_min_mesi, eta_max_mesi),
    CHECK(eta_min_mesi IS NULL OR eta_max_mesi IS NULL OR eta_min_mesi <= eta_max_mesi),
    CHECK(stato_revisione != 'approvata' OR (revisore IS NOT NULL AND length(trim(revisore)) > 0
                                             AND revisionato_il IS NOT NULL))
) STRICT;
CREATE INDEX IF NOT EXISTS idx_prodotto_popolazione ON prodotto_popolazione(prodotto_codice);
-- La colonna eta_minima_anni resta per compatibilità: le età documentate diventano anche righe «adulto/bambino».
INSERT OR IGNORE INTO prodotto_popolazione (prodotto_codice, popolazione, eta_min_mesi, eta_max_mesi, esito, nota,
                                            fonte_id, stato_revisione)
SELECT codice, 'bambino', NULL, eta_minima_anni * 12 - 1, 'controindicato',
       'Sotto ' || eta_minima_anni || ' anni (età minima registrata).', eta_fonte_id, 'candidata'
FROM prodotti WHERE eta_minima_anni IS NOT NULL AND eta_minima_anni > 0 AND eta_fonte_id IS NOT NULL;
INSERT OR IGNORE INTO prodotto_popolazione (prodotto_codice, popolazione, eta_min_mesi, eta_max_mesi, esito, nota,
                                            fonte_id, stato_revisione)
SELECT p.codice, CASE p.specie_destinazione WHEN 'cane' THEN 'cane' ELSE 'gatto' END, NULL, NULL, 'indicato',
       'Medicinale veterinario.', (SELECT fonte_id FROM prodotto_fonti WHERE prodotto_codice = p.codice LIMIT 1), 'candidata'
FROM prodotti p WHERE p.specie_destinazione IN ('cane','gatto')
  AND EXISTS (SELECT 1 FROM prodotto_fonti WHERE prodotto_codice = p.codice);
PRAGMA user_version = 8;
COMMIT;
