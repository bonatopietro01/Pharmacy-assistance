-- Schema v9: origine dell'integratore nel feedback anonimo («farmaco» o «sintomo»).
-- Nessun testo della conversazione: solo l'etichetta dell'origine.
BEGIN;
ALTER TABLE feedback_banco ADD COLUMN origine TEXT CHECK(origine IS NULL OR origine IN ('farmaco','sintomo'));
PRAGMA user_version = 9;
COMMIT;
