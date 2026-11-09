PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE offerte_nuove (
    codice TEXT PRIMARY KEY NOT NULL,
    prodotto_codice TEXT NOT NULL REFERENCES prodotti(codice),
    titolo TEXT NOT NULL CHECK(length(trim(titolo)) > 0),
    criterio TEXT NOT NULL CHECK(length(trim(criterio)) > 0),
    prezzo_cent INTEGER CHECK(prezzo_cent >= 0),
    inizio TEXT,
    fine TEXT,
    stato TEXT NOT NULL CHECK(stato IN ('demo', 'bozza', 'attiva')),
    beneficio TEXT NOT NULL DEFAULT '',
    disponibilita INTEGER NOT NULL DEFAULT 0 CHECK(disponibilita >= 0),
    criterio_tipo TEXT NOT NULL CHECK(criterio_tipo IN ('prodotto','cosmetico','budget')),
    budget_cent INTEGER CHECK(budget_cent >= 0),
    CHECK(prezzo_cent IS NOT NULL OR length(trim(beneficio)) > 0),
    CHECK(stato != 'attiva' OR (inizio IS NOT NULL AND fine IS NOT NULL AND inizio <= fine)),
    CHECK(criterio_tipo != 'budget' OR (budget_cent IS NOT NULL AND prezzo_cent IS NOT NULL))
) STRICT;

INSERT INTO offerte_nuove (codice, prodotto_codice, titolo, criterio, prezzo_cent, inizio, fine,
                          stato, disponibilita, criterio_tipo)
SELECT codice, prodotto_codice, titolo, criterio, prezzo_cent,
       CASE WHEN codice = 'DEMO-OFF-01' THEN COALESCE(inizio, '2026-01-01') ELSE inizio END,
       CASE WHEN codice = 'DEMO-OFF-01' THEN COALESCE(fine, '2099-12-31') ELSE fine END,
       stato, CASE WHEN stato = 'demo' THEN 1 ELSE 0 END,
       CASE WHEN codice IN ('DEMO-OFF-01', 'DEMO-OFF-02') THEN 'cosmetico' ELSE 'prodotto' END
FROM offerte;

DROP TABLE offerte;
ALTER TABLE offerte_nuove RENAME TO offerte;
PRAGMA user_version = 3;
COMMIT;
