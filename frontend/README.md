# Schermata del farmacista

Avvia `AVVIA_BANCO.cmd` e tieni aperta la finestra del server. Se il server è già in esecuzione, usa `APRI_SCHERMATA.url` o [Banco farmacia](http://127.0.0.1:8765/). La schermata è riservata al farmacista e usa un catalogo di prova.

- **Inizia ascolto** attiva il microfono predefinito del PC. La fascia in fondo mostra la fase, il motivo e l’indizio quando disponibile. Il corsivo indica testo provvisorio. **Correggi nome** seleziona una confezione esatta tra i candidati correnti e lascia intatto il testo trascritto.
- Le righe dei prodotti mostrano nome, dati essenziali e sintomi documentati. Seleziona una riga o una confezione per aggiornare il prezzo e le scorte a destra. **Fonti e dettagli** apre il riferimento documentale senza allungare le righe.
- La pausa di ricerca è configurabile in `database/configurazione.json` con `pausa_secondi` (valore iniziale 4). I risultati precedenti restano consultabili finché arriva un nuovo match stabile. **Integratori pertinenti** si apre quando un segnale di chiusura ha un riferimento documentato. La richiesta esplicita di supporto immunitario può mostrare integratori documentati. Le offerte valide compaiono alla cassa in presenza di interesse commerciale esplicito.
- **Termina ascolto** e **Azzera sessione** fermano il microfono e svuotano trascrizione e schede. Se cade il collegamento la pagina rimuove i contenuti; senza contatti la sessione di ascolto scade sul server. Audio e contesto non vengono salvati su disco.
- In **Impostazioni**, scegli separatamente il microfono di ingresso e il motore locale Vosk o Whisper.cpp. La selezione del microfono si applica al successivo avvio dell’ascolto. Per usare OpenAI, seleziona il provider, configura il modello e la chiave e abilita esplicitamente l’invio dei frammenti di testo. La soglia iniziale è 25 parole. Salva le impostazioni prima di usare **Verifica connessione**, che invia solo testo sintetico.

La [pagina tecnica separata](http://127.0.0.1:8765/diagnostica) mostra gli stati di microfono, modello, ricerca, catalogo, server, interfaccia e fonti. **Copia eventi tecnici** copia solo ora UTC, livello, componente, codice e durata; il buffer del server è limitato a 100 eventi in memoria.

Per provare un altro modello Vosk italiano già installato, imposta la variabile `SALES_VOSK_MODEL` al percorso della sua cartella prima di avviare il banco. Il riconoscimento rimane locale. Il confronto riportato nel TaskState usa il modello piccolo già installato.

L’audio usa `vosk`, `sounddevice` e il modello italiano estratto in `models/vosk-model-small-it-0.22/`. Il server cerca i pacchetti anche in `.audio-packages/`. [Modelli Vosk](https://alphacephei.com/vosk/models)

```powershell
$deskPython = Join-Path $env:USERPROFILE 'AppData\Local\Python\pythoncore-3.14-64\python.exe'
& $deskPython -m pip install --target .audio-packages vosk==0.3.45 sounddevice==0.5.6
```

Le richieste interne di reintegro si aprono quando il catalogo ha tre unità o meno. Il file `database/reintegro.sqlite3` conserva codice, nome, quantità e data di apertura. La richiesta è unica per codice e viene chiusa quando il catalogo torna sopra soglia.
