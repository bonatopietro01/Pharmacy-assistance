# Benchmark riconoscimento locale dei prodotti

## Domanda e raccomandazione

Confrontare Vosk, Whisper.cpp e un flusso ibrido per trascrizione italiana breve, riconoscimento di nomi commerciali del catalogo e costo percepito. **Raccomandazione: DATI INSUFFICIENTI per promuovere un motore predefinito.** Lasciare Vosk come scelta rapida e mantenere Ibrido come opzione da provare al microfono. Whisper singolo e il prompt globale del catalogo non sono adatti al flusso continuo osservato in questo campione.

## Scope ed evidenza

- Otto frasi sintetiche pronunciate da Windows OneCore (voce italiana Microsoft Cosimo), generate temporaneamente in WAV PCM mono 16 kHz; durata totale 29,08 s. Nessuna voce di cliente e nessun audio sono stati registrati o mantenuti.
- Vosk small italiano, modello locale `vosk-model-small-it-0.22`; due replay per frase. Whisper.cpp 1.9.5, modello multilingue `ggml-small.bin`, CLI `-l it -t 4 -bo 2`, uguali al numero di thread e best-of mostrati da `whisper-server --help` nel checkout. Una batch senza prompt e una con prompt globale, più un pilot di cinque prompt dinamici.
- La corrispondenza è misurata sui codici recuperati dal catalogo attuale. “Famiglia trovata” significa che il codice atteso è fra i codici restituiti; non equivale a SKU univoco, selezione di confezione o vendita. “SKU univoco” significa che il catalogo restituisce un solo codice atteso.
- Misure dei motori offline: non includono browser, microfono, rete loopback o latenza end-to-end dell’app. Il runtime HTTP di Whisper non è stato raggiungibile nell’ambiente isolato; l’ibrido è stato provato con input audio, server e riconoscitore simulati.
- Il prompt globale è stato escluso dal runtime. Il codice invia solo il miglior nome candidato (soglia similarità 0,60) dalla frase Vosk e soltanto in modalità ibrida.

## Risultati

| Flusso sullo stesso campione | Famiglia trovata | SKU univoco | WER mediano | Tempo osservato |
|---|---:|---:|---:|---|
| Vosk, testo principale | 3/8 | 1/8 | 0,286 | elaborazione mediana 1,234 s; primo partial mediano 0,404 s |
| Whisper.cpp, senza prompt | 7/8 | 5/8 | 0,586 | batch 8 frasi circa 69,2 s |
| Whisper.cpp, prompt globale con 45 nomi | 7/8 | 5/8 | 0,429 | batch 8 frasi 159,248 s |
| Ibrido, replay offline con prompt dinamico | 7/8 | 6/8 | — | non misurabile come runtime: Whisper server loopback non raggiungibile |

Il WER è normalizzato solo per maiuscole, accenti e punteggiatura; non equipara numerali scritti e pronunciati. È perciò una misura del testo complessivo, non un giudizio sul riconoscimento dello SKU. Nel replay Vosk ha trovato Rinazina, Tachipirina e Maalox; il matcher fuzzy del catalogo ha ricomposto “rina cina” come famiglia Rinazina senza inventare un codice di confezione. Whisper senza prompt ha recuperato anche Hirudoid, Zirtec e Canesten. Il prompt dinamico ha corretto il testo di Supradyn in uno SKU univoco. «Granulato effervescente» da solo è rimasto senza prodotto: non basta per dedurre Geffer.

Il prompt globale migliora il testo aggregato ma raddoppia più che il tempo batch e non migliora il richiamo delle famiglie rispetto a Whisper senza prompt. Il campione non include una frase negativa «granulato effervescente» senza Geffer, quindi il rischio di bias da prompt globale resta da misurare. Per questo il runtime invia zero o un candidato basato sulla trascrizione Vosk, mai l’intero catalogo. Nel pilot dinamico il testo dei nomi è diventato più fedele per Rinazina, Tachipirina, Canesten e Supradyn; il miglioramento del catalogo più netto è Supradyn, da cinque codici candidati a uno SKU. Per Geffer non è stato trovato un nome nel testo Vosk e il prompt mirato è rimasto vuoto.

Il replay ibrido evita Whisper se Vosk ha già un solo SKU, usa Whisper per testo non risolto o famiglia ambigua e accetta il nuovo final soltanto se il catalogo restituisce codici compatibili. Il test simulato ha verificato che una frase “a chipirina 500 mg compresse” viene aggiornata a “Tachipirina 500 mg compresse”, con codice `REAL-MED-001` e scheda valorizzata. Non prova la risposta temporale del server Whisper reale.

## Provider locale

Il selettore `provider=local` non usa un modello linguistico locale: la fase deriva da regole deterministiche e prove di conversazione nel backend. Non trascrive né corregge nomi di farmaci, quindi non migliora l’ASR e non aggiunge una chiamata remota. Il matcher locale legge il catalogo/wiki in una cache per sessione; sulle otto frasi il lavoro caldo di analisi ha avuto mediana 54,87 ms su 40 invocazioni. Questo costo è piccolo rispetto all’inferenza Whisper misurata, ma non misura l’intera UI. L’etichetta delle impostazioni ora chiarisce “Regole locali · senza modello”.

## Cambiamenti eseguiti

- Aggiunta la modalità configurabile `ibrido`: Vosk aggiorna i partial; un worker separato può chiedere a Whisper una rifinitura dopo il final, senza bloccare il thread di acquisizione.
- Whisper riceve al massimo una richiesta pendente. Si salta la chiamata se Vosk ha identificato uno SKU univoco; una frase successiva, un errore, un match incompatibile o un risultato arrivato fuori dalla finestra attiva lascia il testo Vosk invariato.
- Il prompt dinamico deriva da un solo nome del catalogo, con token descrittivi e dosaggi esclusi; Whisper non ottiene diagnosi o dati del destinatario.
- Il server riceve il prompt nel campo multipart `prompt` codificato UTF-8. Il server upstream supporta la configurazione dei thread e il prompt iniziale ([README ufficiale](https://github.com/ggml-org/whisper.cpp/blob/master/examples/server/README.md), [implementazione ufficiale](https://github.com/ggml-org/whisper.cpp/blob/master/examples/server/server.cpp)).
- Il valore salvato in `database/configurazione.json` non è stato cambiato. Il nuovo motore si seleziona da Impostazioni e resta locale; audio e testo non vengono persistiti.

## Controlli

- 51 test esistenti: PASS. `compileall backend`, `node --check frontend/desk.js`, `git diff --check` e parsing JSONL dei benchmark: PASS; nessun test file modificato.
- Sessione sintetica con microfono/server simulati: PASS; final Vosk sostituito solo con final Whisper supportato e SKU/display verificati.
- Payload multipart UTF-8 Whisper: PASS con connessione HTTP simulata. Round-trip API di selezione e salvataggio di `ibrido`: PASS su file temporaneo.
- `WhisperServer.start()` con timeout ridotto: `whisper_avvio_timeout`; il loopback del processo locale non è raggiungibile in questo ambiente. Browser locale e microfono reale: NON VERIFICATI.

## Limiti e prossimi esperimenti

Otto frasi con una sola voce sintetica non rappresentano accenti, rumore, distanza dal microfono, sovrapposizione o parlato spontaneo. Il tempo della CLI include il processo di caricamento; la batch del server riutilizzerebbe il modello, ma non è stato possibile misurarla. La prova dinamica ha avviato il processo CLI per ogni frase, quindi il suo wall time non è confrontabile con la batch. Il primo avvio Whisper e il consumo CPU concorrente con Vosk richiedono una misura sul PC e microfono reali. Prima di rendere Ibrido predefinito, provare un elenco fisso con almeno tre letture per frase, includendo falsi candidati da parole generiche, correggere il nome e misurare p50/p95 fino alla scheda.

```yaml
schema_version: agent-benchmark/v1
report_id: sales-agents-asr-2026-11-10
project_id: sales-agents-pharmacy-assistance
evidence_mode: PIPELINE_REALE
execution_status: PARTIAL
versions:
  project_revision: a3b28cb-plus-uncommitted-worktree
  baseline: Vosk small it 0.22; Whisper.cpp 1.9.5 small, no prompt
  candidate: ibrido con prompt dinamico candidato-singolo
  dataset: benchmark sintetico a otto frasi, versione 1
  rubric: match catalogo per famiglia e SKU, WER tokenizzata
agent_map:
  - name: vosk-small-it
    role: ASR locale in streaming
    source: models/vosk-model-small-it-0.22
  - name: whisper.cpp-small
    role: ASR locale final/prompt
    source: .audio-packages/whisper.cpp/Release/ggml-small.bin
  - name: catalog-matcher
    role: fuzzy matching nome e dettagli nel catalogo SQLite/wiki
    source: backend/conversation.py
  - name: local-phase-rules
    role: assegnazione fase deterministica; non ASR e non modello LLM
    source: backend/desk.py, backend/phase_agent.py
workflow:
  - Vosk produce partial e final nel replay in memoria
  - il matcher locale ricava codici documentati dal catalogo
  - nel replay ibrido Whisper è saltato per uno SKU Vosk univoco, altrimenti riceve un prompt dinamico breve
  - un final Whisper è accettato solo con codici compatibili e frase ancora attiva
conditions:
  - Windows, OneCore Microsoft Cosimo, otto WAV sintetici mono PCM 16 kHz, 29.08 secondi totali
  - Vosk replay due volte per frase, Whisper CLI t=4 e best-of=2
  - confronto Whisper batch senza prompt e batch con prompt globale, poi pilot dinamico su cinque frasi
  - nessuna chiamata a provider remoto; microfono e server HTTP reale non usati con successo
predefined_gates:
  - non dedurre un medicinale da sola forma, sintomo o destinatario
  - mantenere originali i partial Vosk; accettare rifinitura solo con match catalogo compatibile
  - nessun audio o trascrizione di conversazioni reali persistito
cases:
  - case_id: case-01
    origin: synthetic Windows TTS
    expected_product_code: REAL-MED-015
    category: nasal spray brand and formulation
  - case_id: case-02
    origin: synthetic Windows TTS
    expected_product_code: REAL-MED-001
    category: strength and tablet formulation
  - case_id: case-03
    origin: synthetic Windows TTS
    expected_product_code: REAL-MED-018
    category: combination product name
  - case_id: case-04
    origin: synthetic Windows TTS
    expected_product_code: REAL-MED-019
    category: granulate product name
  - case_id: case-05
    origin: synthetic Windows TTS
    expected_product_code: REAL-MED-030
    category: topical gel and strength
  - case_id: case-06
    origin: synthetic Windows TTS
    expected_product_code: REAL-MED-022
    category: oral drops brand
  - case_id: case-07
    origin: synthetic Windows TTS
    expected_product_code: REAL-MED-038
    category: topical cream and strength
  - case_id: case-08
    origin: synthetic Windows TTS
    expected_product_code: REAL-SUP-014
    category: supplement brand and line
runs:
  - run_id: vosk-two-replay
    case_ids: case-01..case-08
    result: 3/8 famiglie, 1/8 SKU univoci; median runtime 1.234 s
  - run_id: whisper-no-prompt-batch
    case_ids: case-01..case-08
    result: 7/8 famiglie, 5/8 SKU univoci; batch circa 69.2 s
  - run_id: whisper-global-prompt-batch
    case_ids: case-01..case-08
    result: 7/8 famiglie, 5/8 SKU univoci; batch 159.248 s
  - run_id: whisper-dynamic-prompt-pilot
    case_ids: case-01,case-02,case-04,case-07,case-08
    result: 4/5 famiglie; 3/5 SKU univoci
  - run_id: hybrid-offline-replay
    case_ids: case-01..case-08
    result: 7/8 famiglie, 6/8 SKU univoci; non è test runtime reale
  - run_id: hybrid-code-mock
    case_ids: case-02
    result: snapshot con REAL-MED-001 e display valorizzata
  - run_id: hybrid-config-roundtrip
    case_ids: []
    result: selezione e persistenza temporanea di ibrido PASS
metrics:
  - name: catalog_family_recall
    values: Vosk 3/8; Whisper 7/8; hybrid replay 7/8
    method: expected product code included in catalog matcher result
    limitation: famiglia ambigua non significa SKU selezionato
  - name: exact_sku_recall
    values: Vosk 1/8; Whisper 5/8; hybrid replay 6/8
    method: singleton expected catalog code only
  - name: wer_median
    values: Vosk 0.286; Whisper no prompt 0.586; Whisper full prompt 0.429
    method: token edit distance divided by reference tokens; accents/punctuation removed; numerals not normalized
  - name: whisper_batch_wall_time
    values: no prompt about 69.2 s; global prompt 159.248 s
    method: same eight WAVs, CLI t=4, best-of=2; excludes app and microphone startup
  - name: local_catalog_match_median
    value: 54.87 ms
    method: 40 warmed calls on these eight transcriptions
    limitation: not full session or browser latency
findings:
  - finding_id: F1
    case_ids: case-04,case-05,case-06,case-07,case-08
    defect: Vosk small misses or mangles product brands in the primary transcript
    severity: medium
    evidence: five unmatched product families in the synthetic set; no n-best improvement
    change: optional hybrid fall-back and catalog fuzzy prompt
  - finding_id: F2
    case_ids: case-04,case-08
    defect: full-catalog prompt adds inference cost without improving family recall and varies which brand is recovered
    severity: medium
    evidence: 69.2 s versus 159.248 s batch; Geffer recovered but Supradyn lost
    change: reject global prompt; only provide one candidate grounded in Vosk text
  - finding_id: F3
    case_ids: []
    defect: local provider label implied a local model
    severity: low
    evidence: provider=local only follows deterministic evidence rules; `_schedule_agent` skips non-OpenAI providers
    change: UI label now says local rules without a model
worsened_case_ids: [case-08 for full-catalog prompt; case-07 remains multi-SKU ambiguous]
human_validation:
  - sample: 8 synthetic Windows TTS utterances
    validated: catalog code mappings and one mocked hybrid session
    disagreements: no real pharmacist or real voice sample
recommendation: DATI INSUFFICIENTI
next_experiments:
  - test the same fixed phrases through the real microphone and local HTTP server, three repetitions each
  - measure time from phrase end to stable card and p50/p95 while Vosk continues receiving audio
  - add negative cases containing only generic forms and unrelated product-like words
  - confirm whether a pharmacist wants corrected Whisper finals to replace the Vosk final text
limits:
  - one synthetic voice and eight short scripted phrases
  - CLI wall time includes startup; server inference timing unavailable because loopback was blocked
  - hybrid replay is a routing simulation; hybrid code verification used mocks
  - no real customer audio, browser session, or microphone test
```
