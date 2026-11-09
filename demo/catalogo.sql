PRAGMA foreign_keys = ON;
BEGIN;

CREATE TABLE prodotti (
    codice TEXT NOT NULL PRIMARY KEY,
    nome TEXT NOT NULL,
    categoria TEXT NOT NULL CHECK (categoria IN ('Farmaco da banco', 'Integratore')),
    formato TEXT NOT NULL,
    prezzo_cent INTEGER NOT NULL CHECK (prezzo_cent >= 0),
    quantita INTEGER NOT NULL CHECK (quantita >= 0)
) STRICT;

CREATE TABLE wiki (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    prodotto_codice TEXT UNIQUE REFERENCES prodotti(codice),
    titolo TEXT NOT NULL,
    parole_chiave TEXT NOT NULL,
    testo TEXT NOT NULL
) STRICT;

INSERT INTO prodotti (codice, nome, categoria, formato, prezzo_cent, quantita) VALUES
    ('DEMO-OTC-01', 'Banco Demo A', 'Farmaco da banco', 'Spray', 790, 12),
    ('DEMO-OTC-02', 'Banco Demo B', 'Farmaco da banco', 'Compresse', 980, 4),
    ('DEMO-OTC-03', 'Banco Demo C', 'Farmaco da banco', 'Soluzione orale', 1150, 0),
    ('DEMO-INT-01', 'Integratore Demo A', 'Integratore', 'Capsule', 1290, 8),
    ('DEMO-INT-02', 'Integratore Demo B', 'Integratore', 'Bustine', 1450, 3),
    ('DEMO-INT-03', 'Integratore Demo C', 'Integratore', 'Gommose', 1090, 6);

INSERT INTO wiki (slug, prodotto_codice, titolo, parole_chiave, testo) VALUES
    ('banco-demo-a', 'DEMO-OTC-01', 'Scheda Banco Demo A', 'banco demo a spray',
        'Scheda di prova per una confezione spray. Nel dialogo, il cliente la cita come prodotto già utilizzato. La scheda serve a mostrare come il sistema riconosce un riferimento passato.'),
    ('banco-demo-b', 'DEMO-OTC-02', 'Scheda Banco Demo B', 'banco demo b compresse',
        'Scheda di prova per una confezione di compresse. Nel dialogo, il farmacista sceglie di aprirla per consultare insieme la scheda e la disponibilità di magazzino.'),
    ('banco-demo-c', 'DEMO-OTC-03', 'Scheda Banco Demo C', 'banco demo c soluzione orale scorte esaurito',
        'Scheda di prova per una soluzione orale. Le scorte simulate sono a zero. Il caso permette di controllare che sullo schermo compaia la disponibilità corretta.'),
    ('integratore-demo-a', 'DEMO-INT-01', 'Scheda Integratore Demo A', 'integratore demo a capsule',
        'Scheda anagrafica di prova per un integratore in capsule. Il catalogo fornisce formato, prezzo e quantità disponibili per la consultazione.'),
    ('integratore-demo-b', 'DEMO-INT-02', 'Scheda Integratore Demo B', 'integratore demo b bustine',
        'Scheda anagrafica di prova per un integratore in bustine. Il record permette di filtrare il catalogo per categoria e formato.'),
    ('integratore-demo-c', 'DEMO-INT-03', 'Scheda Integratore Demo C', 'integratore demo c gommose',
        'Scheda anagrafica di prova per un integratore in formato gommoso. Il nome simile a quello di altri record aiuta a verificare che la ricerca apra la scheda selezionata.'),
    ('caso-raffreddore', NULL, 'Dialogo di prova sul raffreddore', 'raffreddore dialogo menzione correzione banco',
        'Il cliente dice «Ho il raffreddore e ho già usato Banco Demo A». Il farmacista dice «Apro la scheda di Banco Demo B», poi «Mi correggo, chiudi la scheda B e apri la C». L''esempio riguarda prodotti fittizi e mette in evidenza uso passato, apertura di una scheda e correzione.'),
    ('lettura-disponibilita', NULL, 'Lettura della disponibilità', 'magazzino disponibilità scorte prezzo esaurito',
        'La quantità rappresenta le unità disponibili nel catalogo di prova. Quando vale zero, la scheda indica «Non disponibile». Una nuova ricerca può aprire un altro prodotto per consultazione.');

CREATE VIRTUAL TABLE wiki_fts USING fts5(
    titolo,
    parole_chiave,
    testo,
    content = 'wiki',
    content_rowid = 'id'
);

INSERT INTO wiki_fts(wiki_fts) VALUES ('rebuild');
COMMIT;
