-- Schema v6. Si applica con: python backend/catalog_setup.py migrate-latest --catalog <copia>
-- Aggiunge i dati che servono a vendere bene al banco senza allentare le regole:
--   1. regime di fornitura ed età minima del prodotto (filtri di ammissibilità);
--   2. protocolli di banco per concetto: domande, segnali d'allarme, consigli, follow-up;
--   3. complementi di banco (cross-selling) revisionabili, separati dalle relazioni cliniche;
--   4. feedback anonimo per misurare cosa funziona;
--   5. registro delle revisioni.
-- È additiva: nessuna colonna o riga esistente viene modificata o cancellata.
-- Applicarla una sola volta (ALTER TABLE non è ripetibile), prima su una copia,
-- come da database/README.md.

PRAGMA foreign_keys = ON;
BEGIN;

-- 1. Ammissibilità -----------------------------------------------------------
-- SOP = senza obbligo di prescrizione, OTC = da banco (automedicazione),
-- RR / RNR = ricetta ripetibile / non ripetibile, vet_RR = ricetta veterinaria.
ALTER TABLE prodotti ADD COLUMN regime_fornitura TEXT NOT NULL DEFAULT 'non_verificato'
    CHECK(regime_fornitura IN ('SOP','OTC','RR','RNR','RRL','vet_RR','vet_libera','non_farmaco','non_verificato'));
ALTER TABLE prodotti ADD COLUMN regime_fonte_id TEXT REFERENCES fonti(id);
ALTER TABLE prodotti ADD COLUMN eta_minima_anni INTEGER CHECK(eta_minima_anni IS NULL OR eta_minima_anni BETWEEN 0 AND 120);
ALTER TABLE prodotti ADD COLUMN eta_fonte_id TEXT REFERENCES fonti(id);

-- Le categorie storiche usano due vocabolari ('Farmaco da banco' vs 'medicinale').
-- La vista espone una categoria canonica senza toccare i record.
CREATE VIEW IF NOT EXISTS v_prodotti_categoria AS
SELECT codice,
       CASE categoria
           WHEN 'Farmaco da banco' THEN 'medicinale'
           WHEN 'Medicinale su prescrizione' THEN 'medicinale'
           WHEN 'Integratore' THEN 'integratore_alimentare'
           WHEN 'Dispositivo medico' THEN 'dispositivo_medico'
           WHEN 'Cosmetico' THEN 'cosmetico'
           ELSE categoria
       END AS categoria_canonica
FROM prodotti;

-- 2. Protocolli di banco ---------------------------------------------------
CREATE TABLE IF NOT EXISTS protocolli_banco (
    concetto_id TEXT PRIMARY KEY NOT NULL REFERENCES concetti(id) ON DELETE CASCADE,
    versione TEXT NOT NULL,
    stato TEXT NOT NULL DEFAULT 'bozza' CHECK(stato IN ('bozza','approvato','ritirato')),
    scheda_wiki TEXT,
    revisore TEXT,
    revisionato_il TEXT,
    CHECK(stato != 'approvato' OR (revisore IS NOT NULL AND length(trim(revisore)) > 0
                                   AND revisionato_il IS NOT NULL))
) STRICT;

CREATE TABLE IF NOT EXISTS protocollo_voci (
    concetto_id TEXT NOT NULL REFERENCES protocolli_banco(concetto_id) ON DELETE CASCADE,
    ordine INTEGER NOT NULL CHECK(ordine >= 0),
    tipo TEXT NOT NULL CHECK(tipo IN ('domanda','red_flag','consiglio','follow_up')),
    testo TEXT NOT NULL CHECK(length(trim(testo)) > 0),
    -- per una domanda: quale filtro alimenta (es. 'eta', 'gravidanza', 'terapie', 'durata')
    filtro TEXT,
    fonte_id TEXT REFERENCES fonti(id),
    PRIMARY KEY (concetto_id, tipo, ordine)
) STRICT;

-- 3. Complementi di banco (cross-selling) ------------------------------------
-- Separati da relazioni_prodotti/complemento_clinico: qui stanno abbinamenti di
-- supporto (igiene, dispositivi, comfort, formato) che il farmacista approva
-- come proposta commerciale. Un complemento può puntare a uno SKU o a una
-- categoria di scaffale quando lo SKU non è ancora in catalogo.
CREATE TABLE IF NOT EXISTS complementi_banco (
    id INTEGER PRIMARY KEY,
    concetto_id TEXT REFERENCES concetti(id) ON DELETE CASCADE,
    prodotto_origine TEXT REFERENCES prodotti(codice) ON DELETE CASCADE,
    prodotto_complemento TEXT REFERENCES prodotti(codice) ON DELETE CASCADE,
    categoria_scaffale TEXT,
    tipo TEXT NOT NULL CHECK(tipo IN ('supporto_igiene','dispositivo','integratore','formato_convenienza','prevenzione')),
    motivo TEXT NOT NULL CHECK(length(trim(motivo)) > 0),
    esclusioni TEXT NOT NULL DEFAULT '',
    priorita INTEGER NOT NULL DEFAULT 100,
    stato_revisione TEXT NOT NULL DEFAULT 'candidata' CHECK(stato_revisione IN ('candidata','approvata','respinta')),
    revisore TEXT,
    revisionato_il TEXT,
    CHECK(concetto_id IS NOT NULL OR prodotto_origine IS NOT NULL),
    CHECK(prodotto_complemento IS NOT NULL OR (categoria_scaffale IS NOT NULL AND length(trim(categoria_scaffale)) > 0)),
    CHECK(stato_revisione != 'approvata' OR (revisore IS NOT NULL AND length(trim(revisore)) > 0
                                             AND revisionato_il IS NOT NULL))
) STRICT;

-- 4. Feedback anonimo ----------------------------------------------------------
-- Nessun testo della conversazione, nessun dato del cliente: solo quale
-- contenuto è stato mostrato e cosa ne ha fatto il farmacista.
CREATE TABLE IF NOT EXISTS feedback_banco (
    id INTEGER PRIMARY KEY,
    creato_il TEXT NOT NULL,
    concetto_id TEXT REFERENCES concetti(id),
    prodotto_codice TEXT REFERENCES prodotti(codice),
    complemento_id INTEGER REFERENCES complementi_banco(id),
    evento TEXT NOT NULL CHECK(evento IN ('mostrato','proposto','accettato','rifiutato','non_pertinente','errore_riconoscimento')),
    protocollo_versione TEXT
) STRICT;
CREATE INDEX IF NOT EXISTS feedback_banco_concetto ON feedback_banco(concetto_id, evento);

-- 5. Registro revisioni ------------------------------------------------------
CREATE TABLE IF NOT EXISTS registro_revisioni (
    id INTEGER PRIMARY KEY,
    tabella TEXT NOT NULL,
    chiave TEXT NOT NULL,
    da_stato TEXT,
    a_stato TEXT NOT NULL,
    revisore TEXT NOT NULL CHECK(length(trim(revisore)) > 0),
    il TEXT NOT NULL,
    nota TEXT NOT NULL DEFAULT ''
) STRICT;

-- 6. Concetti del lessico colloquiale (solo riconoscimento, nessuna relazione) --
INSERT OR IGNORE INTO concetti (id, nome, tipo) VALUES
    ('mal-di-gola', 'Mal di gola', 'sintomo'),
    ('febbre', 'Febbre', 'sintomo'),
    ('dolore-muscolare', 'Dolore muscolare e articolare', 'sintomo'),
    ('dolore-mestruale', 'Dolori mestruali', 'sintomo'),
    ('mal-di-denti', 'Mal di denti', 'sintomo'),
    ('diarrea', 'Diarrea', 'sintomo'),
    ('stitichezza', 'Stitichezza', 'sintomo'),
    ('punture-insetti', 'Punture di insetto e prurito', 'sintomo'),
    ('herpes-labiale', 'Herpes labiale', 'condizione'),
    ('emorroidi', 'Emorroidi', 'condizione'),
    ('stanchezza', 'Stanchezza', 'bisogno'),
    ('sonno', 'Sonno e rilassamento', 'bisogno'),
    ('fermenti-lattici', 'Fermenti lattici', 'bisogno'),
    ('gonfiore-addominale', 'Gonfiore e digestione', 'sintomo');

-- La tabella `wiki` e l'indice `wiki_fts` (8 righe del primo prototipo) non sono
-- più letti dal backend, che indicizza wiki/schede/*.md in memoria. Dopo la
-- verifica si possono rimuovere:
--   DROP TABLE wiki_fts; DROP TABLE wiki;   (fatto dalla migrazione 007)

PRAGMA user_version = 6;
COMMIT;
