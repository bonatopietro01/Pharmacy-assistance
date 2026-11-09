PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;
CREATE TABLE prodotti_nuovi (
    codice TEXT PRIMARY KEY NOT NULL, nome TEXT NOT NULL, categoria TEXT NOT NULL,
    formato TEXT NOT NULL, prezzo_cent INTEGER NOT NULL CHECK(prezzo_cent >= 0),
    quantita INTEGER NOT NULL CHECK(quantita >= 0), principio_attivo TEXT,
    dosaggio TEXT, via TEXT, immagine TEXT,
    fonte TEXT NOT NULL DEFAULT 'Catalogo dimostrativo'
) STRICT;
INSERT INTO prodotti_nuovi (codice,nome,categoria,formato,prezzo_cent,quantita)
SELECT codice,nome,categoria,formato,prezzo_cent,quantita FROM prodotti;
DROP TABLE prodotti;
ALTER TABLE prodotti_nuovi RENAME TO prodotti;
CREATE TABLE relazioni_prodotti (
    origine TEXT NOT NULL REFERENCES prodotti(codice),
    destinazione TEXT NOT NULL REFERENCES prodotti(codice),
    tipo TEXT NOT NULL CHECK(tipo IN ('equivalente_demo','equivalente_documentato','complemento_cosmetico','complemento_revisionato')),
    fonte TEXT NOT NULL, condizioni TEXT NOT NULL, esclusioni TEXT, revisore TEXT,
    PRIMARY KEY (origine,destinazione,tipo),
    CHECK(origine != destinazione),
    CHECK(tipo NOT IN ('equivalente_documentato','complemento_revisionato') OR (revisore IS NOT NULL AND length(trim(revisore)) > 0)),
    CHECK(tipo != 'complemento_revisionato' OR (esclusioni IS NOT NULL AND length(trim(esclusioni)) > 0))
) STRICT;
CREATE TABLE offerte (
    codice TEXT PRIMARY KEY NOT NULL, prodotto_codice TEXT NOT NULL REFERENCES prodotti(codice),
    titolo TEXT NOT NULL, criterio TEXT NOT NULL, prezzo_cent INTEGER NOT NULL CHECK(prezzo_cent >= 0),
    inizio TEXT, fine TEXT, stato TEXT NOT NULL CHECK(stato IN ('demo','bozza','attiva')),
    CHECK(stato != 'attiva' OR (inizio IS NOT NULL AND fine IS NOT NULL AND inizio <= fine))
) STRICT;
INSERT INTO prodotti (codice,nome,categoria,formato,prezzo_cent,quantita,principio_attivo,dosaggio,via) VALUES
    ('DEMO-COS-01','Mascara Demo','Cosmetico','Mascara',1390,8,NULL,NULL,NULL),
    ('DEMO-COS-02','Struccante Demo','Cosmetico','Flacone',890,5,NULL,NULL,NULL),
    ('DEMO-DIS-01','Termometro Demo','Dispositivo medico','Digitale',990,6,NULL,NULL,NULL),
    ('DEMO-EQV-01','Compresse Demo di riferimento','Farmaco da banco','Compresse',850,0,'Sostanza fittizia X','Confezione demo A','Orale'),
    ('DEMO-EQV-02','Compresse Demo alternativa','Farmaco da banco','Compresse',650,7,'Sostanza fittizia X','Confezione demo A','Orale'),
    ('DEMO-RX-01','Ricetta Demo R','Medicinale su prescrizione','Confezione demo',1900,4,'Sostanza fittizia R',NULL,NULL);
INSERT INTO relazioni_prodotti (origine,destinazione,tipo,fonte,condizioni) VALUES
    ('DEMO-EQV-01','DEMO-EQV-02','equivalente_demo','Scenario sintetico','Simula una confezione equivalente per verificare l’interfaccia.'),
    ('DEMO-COS-01','DEMO-COS-02','complemento_cosmetico','Scenario sintetico','Il cliente chiede come rimuovere il trucco.');
INSERT INTO offerte VALUES
    ('DEMO-OFF-01','DEMO-COS-01','Offerta mascara di prova','Interesse dichiarato per il mascara',1190,NULL,NULL,'demo'),
    ('DEMO-OFF-02','DEMO-COS-02','Offerta struccante scaduta di prova','Interesse dichiarato per lo struccante',690,'2026-01-01','2026-01-31','demo');
PRAGMA user_version = 2;
COMMIT;
PRAGMA foreign_keys = ON;
