# Ricerca ibrida nella wiki e trascrizione con faster-whisper

Tutto gira sul PC: nessuna API a pagamento, nessun dato inviato in rete. Internet serve solo **una volta**, per scaricare i modelli; poi funzionano offline (verificato con `HF_HUB_OFFLINE=1`).

## Installazione

```powershell
$deskPython = Join-Path $env:USERPROFILE 'AppData\Local\Python\pythoncore-3.14-64\python.exe'
& $deskPython -m pip install -r requirements.txt
& $deskPython -m backend.wiki_search indicizza
```

Il primo comando installa `sentence-transformers` (con PyTorch per CPU) e `faster-whisper`. Il secondo scarica il modello di embedding e indicizza la wiki (circa 3 minuti la prima volta su questo PC). Il modello Whisper si scarica al primo avvio dell'ascolto con il motore faster-whisper.

## Dove finiscono i modelli e quanto occupano

| Cosa | Dove | Spazio |
|---|---|---|
| `BAAI/bge-m3` (embedding) | `%USERPROFILE%\.cache\huggingface\hub\models--BAAI--bge-m3` | 2,2 GB |
| Whisper `small` (CTranslate2, predefinito senza GPU) | `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-small` | 0,46 GB |
| Whisper `medium` (facoltativo) | `…\models--Systran--faster-whisper-medium` | circa 1,5 GB |
| Whisper `large-v3-turbo` (con GPU NVIDIA) | `…\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo` | circa 1,6 GB |
| Indice dei vettori della wiki | `database/wiki_vettori.sqlite3` (non versionato) | circa 1 MB |
| Pacchetti Python (PyTorch CPU, CTranslate2, transformers, …) | cartella del Python del banco | circa 1,1 GB |

Su Windows senza «Modalità sviluppatore» la cache di Hugging Face non usa link simbolici: al primo download `bge-m3` può lasciare una seconda copia dei pesi (`model.safetensors`, 2,2 GB) in un'altra cartella di `snapshots`. Il banco carica solo quella con `pytorch_model.bin`, quindi l'altra si può cancellare. La cache si può spostare impostando `HF_HOME` prima di avviare il banco.

## 1. Ricerca ibrida nella wiki

- Modulo: `backend/wiki_search.py`. Endpoint: `POST /api/wiki/cerca` con `{"testo": "…"}`.
- Interfaccia: nella **Scheda farmaco** (`/farmaco`) una ricerca per testo mostra in fondo il riquadro **Nella wiki** con pagina, sezione ed estratto. I risultati trovati solo per significato sono marcati «Simile per significato». Le ricerche per solo codice numerico e la telecamera non lo usano.
- Le schede di `wiki/schede/` (le bozze sono escluse, come nella ricerca esistente) vengono divise in sezioni sui titoli Markdown; ogni sezione porta il titolo della pagina.
- I vettori si salvano in `database/wiki_vettori.sqlite3` con un hash SHA-256 di ogni pagina: a ogni ricerca si ricalcolano solo le pagine nuove o modificate. Se cambia il modello, si ricostruisce tutto.
- Classifica finale: **Reciprocal Rank Fusion** (k = 60) tra BM25 (SQLite FTS5, stessa normalizzazione della ricerca esistente) e similarità coseno. Una sigla esatta resta in alto perché compare in entrambe le classifiche; i concetti simili entrano grazie al significato. Al massimo 5 risultati possono arrivare dal solo significato.
- Il modello si carica in background all'avvio del banco (circa 20 s); poi una ricerca richiede circa 150–250 ms.
- Se il pacchetto o il modello mancano, il riquadro dice «Solo parole chiave» e la ricerca continua con BM25.

**Perché `bge-m3`**: il PC non ha una GPU NVIDIA (Intel UHD 620, i7-8665U a 4 core, 16 GB di RAM), quindi all'inizio avevo scelto il più leggero `intfloat/multilingual-e5-base`. Sulle schede reali però `e5-base` dava punteggi quasi uguali a risultati giusti e sbagliati: per «non riesco a dormire» il risultato giusto aveva 0,805 e quelli fuori tema 0,800. Con `bge-m3` lo stacco è netto (0,488 contro una mediana di 0,375). Il costo è accettabile su questo PC: una query richiede circa 150 ms e l'indicizzazione completa circa 3 minuti, fatta una volta sola. In più è lo stesso modello già previsto da `backend/semantica.py`, quindi si scarica una volta per entrambe le funzioni.

Configurazione facoltativa in `database/configurazione.json`:

```json
"ricerca_wiki": {"modello": "BAAI/bge-m3", "semantica": true, "soglia": -1}
```

`"semantica": false` torna alle sole parole chiave. `"soglia"` è la similarità minima per i risultati trovati solo per significato (-1 = nessuna). Una soglia fissa non è il default perché una query di una sola parola come «costi» ottiene circa 0,33 anche sulla sezione giusta.

## 2. Trascrizione con faster-whisper

- Modulo: `backend/speech_faster_whisper.py`. Si sceglie in **Impostazioni → Motore di trascrizione locale → faster-whisper**. Vosk, Whisper.cpp e Ibrido restano invariati e il motore configurato non è stato cambiato.
- Il microfono è già catturato dal server Python, quindi l'audio non passa dal browser e resta in memoria. Non serve avviare altri servizi.
- Lingua fissa italiano; filtro dei silenzi (Silero VAD integrato in faster-whisper) attivo; trascrizione **a fine frase** (dopo circa 0,9 s di silenzio), senza testi provvisori.
- `initial_prompt` generato in automatico (massimo 1000 caratteri): nomi commerciali e principi attivi del catalogo, con priorità, più sigle, termini e titoli brevi della wiki finché c'è spazio.
- Stato a schermo: «In ascolto», «In ascolto · trascrizione in corso…», «Errore di trascrizione» con un messaggio che spiega cosa fare.
- Configurazione facoltativa:

```json
"faster_whisper": {"modello": "auto", "compute_type": "auto", "device": "auto", "beam_size": "auto"}
```

`auto` sceglie `large-v3-turbo` in `float16` con `beam_size` 5 se c'è una GPU NVIDIA; altrimenti `small` in `int8` sulla CPU con `beam_size` 1. Nelle prove `beam_size` 1 ha dato lo stesso testo ed è stato circa il 20% più veloce. `"modello": "medium"` è più preciso ma su questo PC sarebbe circa 3 volte più lento.

### Misure su questo PC (CPU, `small` int8)

Cinque frasi da banco sintetizzate con la voce italiana di Windows (non è una voce reale):

| | Vosk small-it (attuale) | faster-whisper small |
|---|---|---|
| Errori sulle parole | 8/56 (14%) | 5/56 (9%) |
| Nomi commerciali giusti (Tachipirina, Rinazina, NeoBianacid) | 1/3 | 3/3 |
| Tempo per frase | in tempo reale | 4–5 s per 4–6 s di audio |

Senza l'elenco completo del catalogo nel prompt, Whisper scriveva «tacchipirina» e «arinazzina».

## Verifiche

```powershell
& $deskPython -B -m unittest tests.test_wiki_search -v
& $deskPython -m backend.wiki_search cerca "naso chiuso"
```
