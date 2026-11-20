"""Coda di revisione del farmacista per le relazioni sintomo-prodotto.

Le 60 relazioni del catalogo sono tutte `candidata`: finché nessuno le rivede,
il banco le mostra con l'etichetta «non revisionata» e i complementi restano
spenti. Questo strumento rende la revisione un lavoro di pochi minuti al giorno.

    python -m backend.revisione elenco [--concetto raffreddore] [--stato candidata]
    python -m backend.revisione rivedi --revisore "Dott. Mario Rossi" [--concetto tosse]
    python -m backend.revisione riepilogo
    python -m backend.revisione complementi --revisore "Dott. Mario Rossi"
    python -m backend.revisione alias --revisore "Dott. Mario Rossi"

`rivedi` mostra una relazione alla volta (prodotto, indicazione, fonte) e chiede:
  a = approva (chiede le avvertenze principali, obbligatorie per lo schema)
  r = respingi (chiede il motivo)
  s = salta,  q = esci
Ogni decisione è salvata subito; se esiste la tabella `registro_revisioni`
(migrazione 006) viene anche registrata lì. Lavora sempre su una copia finché
il flusso non è stato provato: --catalog percorso/copia.sqlite3
"""

import argparse
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "database" / "farmacia.sqlite3"

_QUERY = """
    SELECT r.concetto_id, c.nome AS concetto, r.prodotto_codice, p.nome AS prodotto,
           r.tipo, r.contesto, r.benefici, r.rischi, r.prerequisiti, r.esclusioni,
           r.stato_revisione, r.revisore, r.revisionato_il, f.url, f.titolo
    FROM relazioni_concetto_prodotto r
    JOIN concetti c ON c.id = r.concetto_id
    JOIN prodotti p ON p.codice = r.prodotto_codice
    LEFT JOIN fonti f ON f.id = r.fonte_id
    WHERE (? IS NULL OR r.concetto_id = ?) AND (? IS NULL OR r.stato_revisione = ?)
    ORDER BY r.concetto_id, p.nome COLLATE NOCASE
"""


def _connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _has_table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _log(db, key, before, after, reviewer, note):
    if _has_table(db, "registro_revisioni"):
        db.execute("""INSERT INTO registro_revisioni (tabella, chiave, da_stato, a_stato, revisore, il, nota)
                      VALUES ('relazioni_concetto_prodotto', ?, ?, ?, ?, ?, ?)""",
                   (key, before, after, reviewer,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"), note))


def elenco(db, concetto=None, stato=None):
    rows = db.execute(_QUERY, (concetto, concetto, stato, stato)).fetchall()
    for row in rows:
        print(f"[{row['stato_revisione']:9s}] {row['concetto_id']:20s} {row['prodotto_codice']:13s} {row['prodotto']}")
    print(f"\n{len(rows)} relazioni")


def riepilogo(db):
    for row in db.execute("""SELECT concetto_id, stato_revisione, count(*) FROM relazioni_concetto_prodotto
                             GROUP BY 1, 2 ORDER BY 1, 2"""):
        print(f"{row[0]:22s} {row[1]:10s} {row[2]}")


def approva(db, concetto, codice, revisore, rischi, nota=""):
    """Approva una relazione. Lo schema esige avvertenze e revisore non vuoti."""
    if not revisore.strip() or not rischi.strip():
        raise ValueError("Revisore e avvertenze sono obbligatori.")
    before = db.execute("""SELECT stato_revisione FROM relazioni_concetto_prodotto
                           WHERE concetto_id=? AND prodotto_codice=? AND tipo='indicazione_etichetta'""",
                        (concetto, codice)).fetchone()
    if before is None:
        raise LookupError(f"Relazione non trovata: {concetto} / {codice}")
    db.execute("""UPDATE relazioni_concetto_prodotto
                  SET stato_revisione='approvata', revisore=?, revisionato_il=?, rischi=?
                  WHERE concetto_id=? AND prodotto_codice=? AND tipo='indicazione_etichetta'""",
               (revisore.strip(), date.today().isoformat(), rischi.strip(), concetto, codice))
    _log(db, f"{concetto}|{codice}", before[0], "approvata", revisore, nota)
    db.commit()


def respingi(db, concetto, codice, revisore, motivo):
    if not revisore.strip() or not motivo.strip():
        raise ValueError("Revisore e motivo sono obbligatori.")
    before = db.execute("""SELECT stato_revisione FROM relazioni_concetto_prodotto
                           WHERE concetto_id=? AND prodotto_codice=? AND tipo='indicazione_etichetta'""",
                        (concetto, codice)).fetchone()
    if before is None:
        raise LookupError(f"Relazione non trovata: {concetto} / {codice}")
    db.execute("""UPDATE relazioni_concetto_prodotto
                  SET stato_revisione='respinta', revisore=?, revisionato_il=?
                  WHERE concetto_id=? AND prodotto_codice=? AND tipo='indicazione_etichetta'""",
               (revisore.strip(), date.today().isoformat(), concetto, codice))
    _log(db, f"{concetto}|{codice}", before[0], "respinta", revisore, motivo)
    db.commit()


def rivedi(db, revisore, concetto=None, ask=input):
    rows = [row for row in db.execute(_QUERY, (concetto, concetto, "candidata", "candidata"))
            if row["tipo"] == "indicazione_etichetta"]
    print(f"{len(rows)} relazioni da rivedere.\n")
    done = 0
    for index, row in enumerate(rows, 1):
        print(f"── {index}/{len(rows)} · {row['concetto']} → {row['prodotto']} ({row['prodotto_codice']})")
        print(f"   Indicazione: {row['benefici'] or row['contesto']}")
        print(f"   Da verificare: {row['prerequisiti']}")
        print(f"   Fonte: {row['titolo'] or '-'}  {row['url'] or ''}")
        choice = ask("   [a]pprova  [r]espingi  [s]alta  [q]esci > ").strip().lower()
        if choice == "q":
            break
        if choice == "a":
            rischi = ask("   Avvertenze principali da mostrare al banco: ").strip()
            if not rischi:
                print("   Avvertenze vuote: relazione saltata.\n")
                continue
            approva(db, row["concetto_id"], row["prodotto_codice"], revisore, rischi)
            done += 1
            print("   ✓ approvata\n")
        elif choice == "r":
            motivo = ask("   Motivo: ").strip()
            if not motivo:
                print("   Motivo vuoto: relazione saltata.\n")
                continue
            respingi(db, row["concetto_id"], row["prodotto_codice"], revisore, motivo)
            done += 1
            print("   ✗ respinta\n")
        else:
            print()
    print(f"Decisioni salvate: {done}")


def _review_rows(db, revisore, rows, describe, decide, ask):
    print(f"{len(rows)} elementi da rivedere.\n")
    done = 0
    for index, row in enumerate(rows, 1):
        print(f"── {index}/{len(rows)} · {describe(row)}")
        choice = ask("   [a]pprova  [r]espingi  [s]alta  [q]esci > ").strip().lower()
        if choice == "q":
            break
        if choice in ("a", "r"):
            note = ask("   Nota (facoltativa): ").strip()
            decide(row, "approvata" if choice == "a" else "respinta", note)
            done += 1
            print("   ✓ salvato\n")
        else:
            print()
    print(f"Decisioni salvate: {done}")


def rivedi_complementi(db, revisore, ask=input):
    if not _has_table(db, "complementi_banco"):
        sys.exit("Il catalogo non ha la tabella complementi_banco: applicare migrate-latest.")
    rows = db.execute("""SELECT c.*, p.nome AS nome_complemento FROM complementi_banco c
                         LEFT JOIN prodotti p ON p.codice = c.prodotto_complemento
                         WHERE c.stato_revisione = 'candidata' ORDER BY c.concetto_id, c.priorita""").fetchall()

    def describe(row):
        target = row["nome_complemento"] or row["categoria_scaffale"]
        origin = row["concetto_id"] or row["prodotto_origine"]
        return f"{origin} → {target} [{row['tipo']}]\n   Motivo: {row['motivo']}\n   Esclusioni: {row['esclusioni'] or '-'}"

    def decide(row, state, note):
        db.execute("""UPDATE complementi_banco SET stato_revisione=?, revisore=?, revisionato_il=? WHERE id=?""",
                   (state, revisore.strip(), date.today().isoformat(), row["id"]))
        db.execute("""INSERT INTO registro_revisioni (tabella, chiave, da_stato, a_stato, revisore, il, nota)
                      VALUES ('complementi_banco', ?, 'candidata', ?, ?, ?, ?)""",
                   (str(row["id"]), state, revisore, datetime.now(timezone.utc).isoformat(timespec="seconds"), note))
        db.commit()

    _review_rows(db, revisore, rows, describe, decide, ask)


def rivedi_alias(db, revisore, ask=input):
    columns = {row[1] for row in db.execute("PRAGMA table_info(alias_prodotto)")}
    if "stato_revisione" not in columns:
        sys.exit("Il catalogo non ha gli alias revisionabili: applicare migrate-latest.")
    rows = db.execute("""SELECT a.*, p.nome FROM alias_prodotto a JOIN prodotti p ON p.codice = a.prodotto_codice
                         WHERE a.stato_revisione = 'candidata' ORDER BY p.nome""").fetchall()

    def describe(row):
        return f"«{row['alias']}» ({row['tipo']}) → {row['nome']} ({row['prodotto_codice']})"

    def decide(row, state, note):
        db.execute("""UPDATE alias_prodotto SET stato_revisione=?, revisore=?
                      WHERE prodotto_codice=? AND alias=? AND tipo=?""",
                   (state, revisore.strip(), row["prodotto_codice"], row["alias"], row["tipo"]))
        _log(db, f"alias|{row['prodotto_codice']}|{row['alias']}", "candidata", state, revisore, note)
        db.commit()

    _review_rows(db, revisore, rows, describe, decide, ask)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", choices=("elenco", "rivedi", "riepilogo", "complementi", "alias"))
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--concetto")
    parser.add_argument("--stato")
    parser.add_argument("--revisore")
    args = parser.parse_args(argv)
    with closing(_connect(args.catalog)) as db:
        if args.comando == "elenco":
            elenco(db, args.concetto, args.stato)
        elif args.comando == "riepilogo":
            riepilogo(db)
        else:
            if not args.revisore:
                sys.exit("Indicare --revisore \"Nome del farmacista\".")
            if args.comando == "complementi":
                rivedi_complementi(db, args.revisore)
            elif args.comando == "alias":
                rivedi_alias(db, args.revisore)
            else:
                rivedi(db, args.revisore, args.concetto)


if __name__ == "__main__":
    main()
