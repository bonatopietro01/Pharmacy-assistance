# Whisper.cpp locale

L’app include l’adattatore al server ufficiale Windows x64 whisper.cpp release b5454 e il modello multilingue `ggml-small.bin`, installati localmente in `.audio-packages/whisper.cpp/Release/`. La verifica dell’installazione ha dato `WhisperServer.available() = True`. Vosk resta il motore predefinito; Whisper.cpp è selezionabile in Impostazioni.

SHA-256:

- Archivio binario ufficiale: `6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb`
- Modello `ggml-small.bin`: `1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b`

Il server viene avviato solo su `127.0.0.1` con lingua italiana. Il frontend non invia l’audio a un servizio remoto. Cattura, WAV, finestre parziali e testo restituito restano nella memoria del processo. I log contengono soltanto codici tecnici, mai audio o trascrizioni. L’adattatore usa il percorso `/` previsto dalla release b5454 installata e invia l’audio a `/inference` in memoria, senza attivare la conversione tramite file temporanei.

Verifica eseguita: avvio del server locale e inferenza completati con un WAV sintetico di silenzio creato in memoria (11 secondi totali). Il risultato `[Musica]` conferma il percorso tecnico e il caricamento del modello, ma non misura la precisione del riconoscimento. Non sono stati provati parlato italiano, latenza su una frase, browser o microfono reale. Mantenere Vosk come predefinito finché queste prove non confermano la qualità e la velocità necessarie al banco.

Fonte: [release ufficiali whisper.cpp](https://github.com/ggml-org/whisper.cpp/releases), [codice server della release b5454](https://github.com/ggml-org/whisper.cpp/blob/d1be6fde11ac6e0407606b4e42fe72d34add8037/examples/server/server.cpp) e [modello ufficiale](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin).
