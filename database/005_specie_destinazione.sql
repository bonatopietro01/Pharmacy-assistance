BEGIN IMMEDIATE;

ALTER TABLE prodotti
    ADD COLUMN specie_destinazione TEXT
    CHECK(specie_destinazione IN ('umana','cane','gatto','cane_gatto'));

UPDATE prodotti
   SET specie_destinazione = 'umana'
 WHERE categoria IN ('medicinale','Farmaco da banco','Medicinale su prescrizione');

PRAGMA user_version = 5;
COMMIT;
