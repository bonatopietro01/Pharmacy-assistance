# Catalogo e wiki di prova

La base contiene sei prodotti fittizi, tre farmaci da banco e tre integratori, con formato, prezzo e disponibilità simulati. La wiki comprende una scheda per prodotto e due pagine trasversali. Ogni pagina relativa a un prodotto è collegata al suo codice di catalogo.

- [Database SQLite](farmacia-demo.sqlite3)
- [Wiki da leggere](WIKI.md)
- [Sorgente del catalogo e della wiki](catalogo.sql)

La ricerca della wiki usa l'indice FTS5 dentro SQLite. Il database e la vista Markdown sono copie di consultazione generate da `catalogo.sql`. Per aggiornare i dati di esempio si modifica quella sorgente e si rigenerano le copie, così l'indice riflette i contenuti della wiki. [Documentazione SQLite FTS5](https://www.sqlite.org/fts5.html)

Per vedere i prodotti e cercare «raffreddore» dal terminale PowerShell, apri la radice di Sales Agents ed esegui questi comandi con il Python installato sul computer.

```powershell
$salesDemoPython = Join-Path $env:USERPROFILE 'AppData\Local\Python\pythoncore-3.14-64\python.exe'
& $salesDemoPython -X utf8 -m sqlite3 'demo\farmacia-demo.sqlite3' 'SELECT codice, nome, categoria, prezzo_cent, quantita FROM prodotti ORDER BY codice;'
& $salesDemoPython -X utf8 -m sqlite3 'demo\farmacia-demo.sqlite3' "SELECT w.titolo, w.testo FROM wiki_fts JOIN wiki w ON w.id = wiki_fts.rowid WHERE wiki_fts MATCH 'raffreddore' ORDER BY rank;"
```

Per rigenerare il database in un file separato, dalla radice esegui il comando seguente. L'apertura esclusiva del file evita di sovrascrivere una copia esistente.

```powershell
@'
from contextlib import closing
from pathlib import Path
import sqlite3

source = Path('demo/catalogo.sql').read_text(encoding='utf-8')
output = Path('demo/farmacia-demo-rigenerato.sqlite3')
output.touch(exist_ok=False)
try:
    with closing(sqlite3.connect(output)) as db:
        db.executescript(source)
except (OSError, sqlite3.Error):
    output.unlink(missing_ok=True)
    raise
'@ | & $salesDemoPython -
```
