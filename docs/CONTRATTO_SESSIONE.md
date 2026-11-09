# Contratto della sessione al banco

Questo contratto è valido per la prova locale descritta in `docs/PROMPT_IMPLEMENTAZIONE.md`. Non introduce servizi remoti o dati clinici reali.

## Snapshot

`/api/stato` restituisce sempre lo snapshot completo corrente:

```json
{
  "schema_version": 1,
  "session_id": "id volatile non registrato",
  "version": 1,
  "action_version": 0,
  "status": {"session": "raccogliendo", "microphone": "attivo", "error_code": null},
  "transcript": {
    "revision": 1,
    "final_segments": [{"text": "..."}],
    "partial": {"text": "..."},
    "testo": "testo finale e ipotesi parziale correnti"
  },
  "phase": {"value": "Raccolta", "source": "auto", "reason": "...", "missing": []},
  "recipient": {"kind": "sconosciuto", "relation": null, "declared_fields": {}, "source": "unknown"},
  "evidence": [{"id": "...", "kind": "product_mention", "span": {"start": 0, "end": 0, "transcript_revision": 1}, "state": "active", "reason": "...", "product_codes": ["..."], "matched_term": "...", "matched_term_basis": "product_name", "mention_context": "neutral", "source": {"kind": "catalog", "id": "...", "label": "..."}}],
  "cards": [{"id": "...", "state": "provisional", "evidence_ids": [], "source": {}, "reason": "...", "product_codes": []}],
  "product": {"candidate_code": null, "selected_code": null, "confirmed_code": null, "confirmed_by": null, "current_code": null, "current_state": "none", "display": null, "commercial": {"bank_price_cents": null, "bank_price_source": null, "stock": null, "stock_source": null, "complements": []}},
  "cart": {"items": [], "item_count": 0, "total_cents": 0, "partial": false, "original_total_cents": 0, "original_partial": false, "savings_cents": 0},
  "symptom_matches": [],
  "desk_results": {"previous": false, "rows": [], "preferred_code": null, "supplements": [], "recognized_name": null},
  "sales_stage": "questions",
  "offers": [], "stock": [], "service": {"kind": null, "comune": "", "data": "", "status": "idle", "answer": null, "source": null}, "restock": []
}
```

Gli offset `start`/`end` sono half-open e contati in unità UTF-16 JavaScript sul campo `transcript.testo`; `transcript_revision` lega l’evidenza al testo esatto. L’AI Engineer può restituire offset Python codepoint, che il Backend converte prima di inviarli.
`product_codes` contiene gli identificativi di catalogo collegati all’evidenza. Per i match di prodotto, `matched_term`, `matched_term_basis` e `source` indicano il termine e la sua provenienza; le basi ammesse distinguono nome/codice, alias di catalogo, principio attivo, ingrediente di integratore e alias di scheda demo. `mention_context` è presente soltanto per `product_mention` e vale `neutral` o `excluded`; non sostituisce lo stato della scheda e non rappresenta un consiglio.

Un elemento `symptom_matches` ha questa forma essenziale:

```json
{
  "concept_id": "raffreddore",
  "concept_name": "Raffreddore",
  "relation_type": "indicazione_etichetta",
  "review_status": "candidata",
  "evidence_id": "conversation.topic:...",
  "evidence_state": "active",
  "span": {"start": 0, "end": 12, "transcript_revision": 1},
  "matched_term": "raffreddore",
  "product_code": "REAL-MED-006",
  "product_display": {"code": "REAL-MED-006", "name": "..."},
  "claim": "Indicazione riportata dalla fonte ...",
  "context": "...",
  "risks": "...",
  "prerequisites": "...",
  "exclusions": "...",
  "source": {"id": "...", "url": "https://...", "title": "...", "owner": "...", "version": "..."},
  "source_version": "..."
}
```

`evidence_state` può essere `active` o `provisional` soltanto dopo il ritardo minimo e il tempo di stabilità del topic. Le UI accettano il match solo se ID, stato, span e revisione corrispondono all’evidenza corrente. Le claim del produttore restano tali e non sono riscritte come fatti clinici verificati dal farmacista.

`desk_results` è la proiezione per il banco compatto. Ogni riga contiene `code`, `display`, `commercial`, `relevance`, `symptoms`, `references` e `variants`. Il codice preferito è nullo in caso di ambiguità. La pertinenza esprime la copertura documentale del contesto e l’identificazione vocale ha un’indicazione separata. Le confezioni hanno codice, etichetta, display e dati commerciali propri. La scelta nella UI cambia il pannello commerciale e non conferma un consiglio.

`previous=true` conserva un risultato da consultare mentre la ricerca riparte con un segmento vuoto. I riferimenti conservati non sono evidenze della revisione attiva. `supplements` si popola dopo un segnale di chiusura solo con un bisogno attivo documentato o un abbinamento approvato con un prodotto identificato. Stop, reset e nuova sessione azzerano anche questa proiezione.

Ogni riga espone `affinity_percent` e gli elenchi `covered_symptoms` e `uncovered_symptoms`. Il denominatore include i concetti sintomo positivi e distinti del contesto attivo. Forma e classificazione documentata sono in `display`. `preference_codes` evidenzia gli SKU compatibili con una preferenza esplicita senza modificare la percentuale.

`voice_choice` porta codice esatto, codice della riga, sezione e token della scelta stabile. `voice_options` espone gli SKU quando il riferimento non è univoco. La scelta aggiorna la consultazione commerciale e non conferma la vendita. Con `phase: "offer"`, `offers` aggiunge righe con promozioni valide e compatibili con un interesse commerciale esplicito. «Non mi serve altro» ritira le proposte. I riferimenti clinici non forniscono criteri commerciali.

`desk_phase` descrive la fase a schermo con `key`, `label`, `reason`, `evidence_id` e `source`. Le chiavi sono `clarify`, `research`, `choose`, `extras` e `closing`. Le richieste di extra e il passaggio alla cassa sono segnali distinti. Gli integratori documentati sono consultabili nella fase extra. Le promozioni del banco compaiono al passaggio esplicito alla chiusura quando sono disponibili e correlate all’interesse commerciale. Un rifiuto ritira le proposte.

Vosk è il motore locale predefinito. Whisper.cpp è opzionale, si può scegliere dalle impostazioni solo quando sono presenti `whisper-server.exe` e il modello multilingual `ggml-small.bin`; in caso di errore l’ascolto ripiega su Vosk. La pipeline Whisper prepara finestre WAV in RAM, invia audio solo a un server legato a loopback e invia partial/final al medesimo flusso volatile di `ingest`. Non scrive audio o trascrizioni su disco o nei log. La qualità e la latenza di Whisper non sono considerate verificate finché non si prova il microfono reale.

La trascrizione originale resta il testo principale. Le ipotesi acustiche secondarie possono aggiungere righe a `desk_results.correction_options` esclusivamente per **Correggi nome**. Le ipotesi secondarie non cambiano fase, sintomi, catalogo o selezione automatica. L’azione `correggi_nome` con `payload.code` accetta soltanto uno SKU visibile nel contesto attivo e riallinea la consultazione a schermo e sul server senza confermare la vendita. Il codice confermato dall’azione appare in `manual_corrected_code`.

`version` cresce a ogni modifica visibile dello snapshot. `action_version` cresce soltanto dopo un’azione accettata del farmacista o la sostituzione della sessione; evita che normali aggiornamenti parziali invalidino un clic appena eseguito. La UI applica solo snapshot con lo stesso `session_id` e `version` crescente.

## Azioni

- `POST /api/inizia`: crea un `session_id` nuovo e avvia il microfono locale.
- `POST /api/stato`: restituisce snapshot completo e rinnova la lease di attività.
- `POST /api/azione`: body `{session_id, expected_action_version, action, payload}`. Azioni ammesse: `fase`, `destinatario`, `seleziona_prodotto`, `conferma_prodotto`, `correggi_prodotto`, `correggi_nome`, `servizio`, `aggiungi_carrello`, `rimuovi_carrello`, `applica_offerta`, `reset`, `termina`.
- Un ID sessione o `action_version` superato non applica l’azione e restituisce `409` con lo snapshot corrente.
- `POST /api/cerca`: ricerca manuale volatile; non registra testo o risultati in log o database.
- `GET /api/offerte` / `POST /api/offerte`: lettura e modifica delle sole offerte dimostrative locali, con validazione server.
- `GET /api/configurazione` / `POST /api/configurazione`: legge o aggiorna URL pubblici, ritardo di attesa e `pausa_secondi` (da 1 a 30 s). Nessun segreto o dato conversazionale è salvato.
- `GET /api/impostazioni` / `POST /api/impostazioni`: configurazione agente con `provider`, `model`, `enabled`, `word_threshold` (5–200, valore iniziale 25), `speech_engine` (`vosk` o `whisper.cpp`) e `input_device`. `input_device=null` indica il predefinito del sistema; un ID stringa seleziona un ingresso elencato in `input_devices`. L’ID deriva da host API e nome normalizzato, con un ordinale per distinguere dispositivi omonimi. La risposta include `input_devices` (ID, nome, canali e indicazione del predefinito), `input_device_missing`, `api_key_configured`, `whisper_available` e `speech_active_engine`, mai il segreto. Una preferenza scollegata è esposta come `input_device=null` e `input_device_missing=true`; l’avvio dell’ascolto riporta `status.error_code=dispositivo_input_non_disponibile` finché il farmacista non salva un ingresso disponibile o il predefinito. La selezione viene risolta nuovamente all’avvio e vale per Vosk e Whisper.cpp. Il POST può impostare `api_key` o rimuovere la chiave protetta con `clear_api_key`. `POST /api/impostazioni/verifica` usa una frase sintetica e la configurazione salvata.

Il flusso locale è il predefinito. Con OpenAI attivato esplicitamente, il server invia solo frammenti finalizzati nuovi (fino a 2400 unità UTF-16) e un elenco limitato di evidenze. Le transizioni esplicite possono anticipare la soglia. Le risposte in ritardo vengono scartate se cambiano sessione, revisione, segmento o configurazione. L’agente remoto può aggiornare la fase visiva nel perimetro delle evidenze validate. La chiave locale è protetta per utente tramite Windows DPAPI e non entra in SQLite, risposte o log.
- `GET /api/diagnostica`: espone soltanto stati tecnici e eventi allowlistati.

Per allineare i chiamanti, i nomi di `action` e i payload sono:

| `action` | `payload` |
|---|---|
| `fase` | `{"value":"Raccolta"}` oppure una fase ammessa |
| `destinatario` | `{"kind":"sconosciuto"}` oppure `{"kind":"sé"}` / `{"kind":"altra_persona","relation":"figlio","declared_fields":{"age":14,"gender":"donna"}}`; solo valori inseriti o confermati dal farmacista |
| `seleziona_prodotto` | `{"code":"codice catalogo"}` |
| `conferma_prodotto` | `{"code":"codice catalogo"}` |
| `correggi_prodotto` | `{"code":null}` o codice corretto |
| `aggiungi_carrello` | `{"code":"SKU esatto visibile nella sessione"}` |
| `rimuovi_carrello` | `{"code":"SKU esatto nel carrello"}` |
| `applica_offerta` | `{"code":"SKU nel carrello","offer_code":"codice offerta visibile alla cassa"}` |
| `scheda` | `{"id":"id scheda","locked":true}`; il blocco o rilascio è una scelta del farmacista |
| `servizio` | `{"kind":"turni","comune":"Milano","data":"2026-11-07"}`; campi pubblici inseriti dall’operatore |
| `reset` / `termina` | `{}` |

`POST /api/cerca` riceve `{"testo":"..."}` e restituisce lo snapshot aggiornato; il testo è effimero. `GET /api/offerte` restituisce `offerte`, prodotti selezionabili e data locale; `POST /api/offerte` salva o disattiva un’offerta con validazione lato server. L’offerta ha `criterio_tipo` (`prodotto`, `cosmetico`, `budget`), criterio commerciale, beneficio, prezzo, periodo e disponibilità. `GET /api/configurazione` restituisce `ritardo_secondi`, `pausa_secondi` e `fonti` (`turni`, `orari`, `sito`); il POST aggiorna questi campi. I campi URL sono destinazioni pubbliche HTTPS senza credenziali e possono usare solo segnaposti `{comune}` e `{data}`. I link esterni sono aperti dal browser solo dopo un’azione dell’operatore e ricevono esclusivamente i campi pubblici compilati in quella sezione. Il sistema non legge né verifica automaticamente la pagina esterna; l’interfaccia deve indicarlo.

`cart` è parte dello snapshot ma resta in memoria. Ogni riga contiene SKU, nome, confezione, quantità, prezzo unitario e provenienza, eventuale offerta applicata e subtotale; prezzo assente produce un totale parziale esplicito. Lo SKU deve essere presente nel catalogo e visibile nella sessione. Una seconda aggiunta dello stesso SKU incrementa la quantità. Rimozione e reset aggiornano il totale; il reset apre una sessione vuota. Nessuna azione del carrello persiste testo, scarica scorte, registra una vendita o modifica SQLite.

Il dispositivo di ingresso è una preferenza locale separata dal motore di trascrizione. Il backend usa lo stesso dispositivo selezionato e la relativa frequenza di campionamento con entrambi i motori. La modifica si applica al successivo avvio dell’ascolto; il flusso già aperto non cambia dispositivo a metà sessione. Se l’ingresso configurato non è disponibile, lo stato tecnico indica l’errore senza registrare il nome del dispositivo, audio o trascrizione.

Le offerte nella fase di chiusura richiedono un interesse commerciale esplicito sullo SKU oppure quello SKU esatto già nel carrello. Il server ricontrolla validità temporale, disponibilità dell’offerta e giacenza prodotto al momento dell’applicazione. Una promozione è applicata solo allo SKU dichiarato dall’offerta; non si sostituiscono formulazioni o confezioni.

## Sessione, sintomi e prodotti

- Ogni avvio crea una sessione nuova. Ogni partial sostituisce la partial precedente; un final viene aggiunto a `final_segments`.
- Ogni lavoro d’interpretazione porta `session_id` e `transcript.revision`; il risultato viene scartato se uno dei due non è più corrente.
- Schede automatiche restano provvisorie finché il farmacista non conferma esplicitamente il prodotto. Una correzione ritira la conferma e i collegamenti che dipendono da essa.
- Una corrispondenza esatta, univoca e stabile con un prodotto del catalogo può valorizzare `product.current_code` e `product.display` anche quando la frase è una menzione neutra. `candidate_code` resta riservato ai segnali espliciti di richiesta/proposta/accettazione; la menzione informativa non equivale a un consiglio o a una vendita.
- Un alias di prodotto demo può provenire solo da una scheda demo esplicitamente collegata, con termine specifico e provenienza della scheda. Termini di forma o generici come “compresse” non identificano un prodotto. Per i prodotti reali valgono i nomi/codici e gli alias o ingredienti di catalogo con fonte adeguata; i termini editoriali della wiki non diventano alias reali.
- Il renderer del banco usa `product.current_code` e `product.display` per mostrare l’identità del prodotto accanto alla trascrizione. `product_display()` può fornire nome e altri campi supportati; i dettagli non supportati restano omessi o nulli e non impediscono la scheda.
- `symptom_matches` è distinto da `product.current_code` e `candidate_code`. Contiene solo relazioni esplicite in `relazioni_concetto_prodotto`, con `tipo=indicazione_etichetta`, stato `candidata`, fonte ufficiale identificabile e claim fonte in stato `verificata` che dice soltanto quanto la fonte documenta. In schema v4 la claim fonte è registrata come `associazione_clinica`; questo non approva la relazione candidata. Ogni match include l’evidenza `topic` attiva e stabile, lo span della revisione corrente, codice e display del prodotto, stato della relazione e fonte consultabile.
- Un match candidato può comparire senza approvazione del farmacista perché è una corrispondenza documentale destinata al farmacista. La UI indica lo stato con la dicitura di sezione «Riferimenti documentali non revisionati»; non deve chiamarlo consiglio, prodotto ideale o raccomandazione, né usare l’ordinamento documentale come priorità clinica. La relazione resta `candidata` nel database; non diventa `approvata` per essere visualizzata.
- Una parola provvisoria non supera il ritardo e la stabilizzazione configurati. La menzione neutra di un prodotto non attiva `symptom_matches`, offerte o complementi. Il tema del sintomo può attivare soltanto i prodotti collegati esplicitamente a quel concetto con la relativa fonte; non si deducono collegamenti da co-occorrenza, da una pagina wiki generica o da un altro sintomo.
- Negazione, uso passato, rifiuto, correzione, ambiguità o cambio di sessione ritirano i `symptom_matches` che dipendono dall’evidenza non più attiva. Se nella stessa frase sono rilevati più prodotti, il sistema non ne sceglie uno arbitrariamente.
- Una frase ambigua non crea una nuova selezione: se non esisteva un prodotto corrente, la scheda resta vuota; se esiste già un prodotto stabile, la scheda precedente resta visibile finché una nuova corrispondenza stabile o un ritiro pertinente non la sostituisce.
- Negazioni, rifiuti, riferimenti a uso passato e correzioni ritirano il prodotto divenuto non pertinente. Una menzione neutra stabile successiva può sostituire il prodotto corrente e azzerare il precedente `candidate_code`.
- Fase e destinatario riportano origine `auto`, `dichiarato`, `manuale` o `unknown`. Attributi mancanti restano sconosciuti.
- Il genere può essere presente solo quando è dichiarato o confermato come attributo del destinatario, con evidenza/provenienza; non si deduce da audio, voce, pronomi o accordo grammaticale. Genere, età e condizioni non pilotano offerte e non bastano per selezionare un medicinale.
- La selezione di equivalenti usa solo la relazione esatta del catalogo. `equivalente_demo` si mostra soltanto con etichetta sintetica; non è equivalenza clinica.
- I collegamenti sintomo-prodotto candidati possono essere mostrati con fonte e stato non revisionato secondo il contratto `symptom_matches`. I complementi clinici e di vendita restano invece esclusi finché non sono approvati; le offerte attive richiedono validità, disponibilità e prova d’interesse commerciale esplicito sul prodotto e non usano salute o demografia.
- I servizi non hanno una risposta automatica senza fonte configurata. Comune e data provengono da campi compilati dal farmacista e sono gli unici campi eventualmente aggiunti al link pubblico di consultazione.
- Un lease senza attività per 12 secondi ferma il microfono e azzera i dati temporanei. Stop, reset, chiusura e nuova sessione applicano la stessa pulizia.
- Gli eventi diagnostici contengono ora, livello, durata, componente e codice tecnico fisso. Non contengono session ID, testo, query, stack trace, dati destinatario o parametri privati.
