# Prompt completo · Miglioramento di Pharmacy-assistance

Questo prompt raccoglie in un'unica sequenza di lavoro tutti i miglioramenti emersi finora: l'analisi dei pain point, il piano di miglioramento con le nuove soluzioni, ricerca e analisi della vendita (prodotto → integratore → offerta), visualizzazione, dati e voce. Sostituisce docs/PROMPT_VENDITA_RICERCA.md.

## 0. Prima di iniziare

Lavora sul repository Pharmacy-assistance. Leggi nell'ordine: AGENTS.md, docs/PROJECT_BRIEF.md, docs/TaskState.md, database/README.md, wiki/README.md, wiki/PROTOCOLLI_DI_BANCO.md, docs/WHISPER_CPP.md. Poi il codice: backend/knowledge.py, backend/conversation.py, backend/desk.py (in particolare `_desk_supplements`, `_refresh_supplement_followup`, `_desk_offers`, `_refresh_offers`), backend/offers.py, backend/cart.py, backend/phase_agent.py, backend/revisione.py, frontend/desk.js, database/lessico-concetti.json, database/006_vendita_protocolli.sql, tests/eval_retrieval.py.

Lancia subito `python -B -m unittest discover -s tests -q` (51 test, oggi tutti verdi) e `python -B tests/eval_retrieval.py` e annota i risultati come base di confronto.

## 1. Obiettivo

Un assistente che, mentre il farmacista parla con il cliente, capisce il bisogno e accompagna la vendita in tre tempi, sempre in quest'ordine:

1. **Prodotto principale**: opzioni ammissibili per il bisogno e il destinatario dichiarato.
2. **Integratore o complemento correlato**: dopo la conferma del prodotto, **uno solo**, approvato e disponibile.
3. **Offerta**: in chiusura, solo sui prodotti già entrati nella conversazione.

Lo schermo deve leggersi in pochi secondi e il farmacista resta sempre chi decide.

## 2. Già fatto (non rifarlo, costruiscici sopra)

| Area | Stato attuale |
|---|---|
| Negazioni | Una negazione conta solo se precede il sintomo nella stessa sotto-frase, entro 6 parole (`_symptom_excluded` in conversation.py). «Mal di testa che non passa» resta un sintomo. |
| Lessico | `database/lessico-concetti.json` (frasi + radici) caricato all'avvio; 14 concetti nuovi solo di riconoscimento: mal-di-gola, febbre, dolore-muscolare, dolore-mestruale, mal-di-denti, diarrea, stitichezza, punture-insetti, herpes-labiale, emorroidi, stanchezza, sonno, fermenti-lattici, gonfiore-addominale. |
| Ricerca manuale | FTS5 con stopword italiane, troncamento leggero dei suffissi, indice in cache invalidato quando cambiano catalogo o wiki (da 20–40 ms a circa 1 ms). |
| Relazioni approvate | `symptom_product_matches` mostra anche le relazioni `approvata` con revisore, senza l'etichetta «non revisionata». |
| Revisione | `python -m backend.revisione rivedi --revisore "…"` per le 60 relazioni candidate. |
| Misura | `tests/eval_retrieval.py`: 47/47 sul golden set (usato per tarare), 15/20 su frasi mai viste (prima 4/20), 0 falsi positivi su 8 frasi neutre. |
| Schema | `database/006_vendita_protocolli.sql` scritto e provato su copia, **non applicato**: regime di fornitura, età minima, protocolli di banco, complementi di banco, feedback anonimo, registro revisioni. |
| Wiki | Formato dei protocolli di banco ed esempio in bozza `wiki/schede/protocollo-raffreddore.md`. |

## 3. Pain point ancora aperti

- **Voce**: Vosk riconosce la famiglia di prodotto in 3 frasi su 8 del benchmark; nessuna prova con microfono reale al banco.
- **Ammissibilità**: tutti i 100 prodotti reali hanno `stato_regolatorio = non_verificato`; nessun campo distingue SOP/OTC da ricetta (es. Elocon). I veterinari iniettabili (Solensia, Librela) non sono vendibili al banco.
- **Revisione ferma**: 60 relazioni tutte `candidata`, nessun revisore nominato.
- **Cross-selling a zero**: `relazioni_prodotti` ha solo 2 righe demo; la fase extra non mostra mai niente.
- **Copertura**: 26 medicinali umani su 55 senza concetto; «dermatite» senza prodotti; solo 3 integratori su 19 collegati a un bisogno; i 14 concetti nuovi non hanno ancora relazioni con fonte; mancano best-seller come Moment e Oki e tutto il parafarmaco di supporto.
- **Alias**: 58 prodotti reali su 100 senza alias; nessun alias d'uso comune né storpiature tipiche del riconoscimento vocale.
- **Dati**: categorie in due vocabolari diversi; 0 immagini su 112 prodotti; prezzi e giacenze di prova; tabelle `wiki` e `wiki_fts` non più lette dal backend.
- **Wiki**: 100 schede su 118 senza `termini`; 44 sono solo la riga del catalogo; nessun protocollo pubblicato.
- **Codice**: desk.py 134 KB e conversation.py 57 KB difficili da far evolvere; docs/TaskState.md 40 KB.

## 4. Regole da non violare

- Il farmacista decide; l'agente mostra fonti, domande e opzioni. Niente scelta terapeutica automatica, niente dosi calcolate per il paziente. Descrivi lo strumento, nell'interfaccia e nei documenti, come supporto alla consultazione per il farmacista: lo scopo dichiarato decide se il software diventa un dispositivo medico (guida MDCG 2019-11).
- Audio, trascrizione e contesto restano in memoria, come oggi. Nessun invio a servizi esterni. Il feedback salvato è anonimo: concetto, codice prodotto, evento, ora. Mai testo della conversazione o dati del cliente.
- Un prodotto compare solo da una relazione con fonte. Una relazione `candidata` resta etichettata «non revisionata».
- Un integratore compare solo da un abbinamento approvato con revisore e fonte. Mai per compensare un effetto indesiderato del prodotto principale.
- Le offerte non usano mai salute, età o genere, né dichiarati né dedotti. Selezione clinica e promozione restano separate nel codice e sullo schermo.
- Le preferenze commerciali (margine, offerta, giacenza alta) ordinano solo opzioni già ammissibili.
- Ogni modifica al database passa da una migrazione numerata, provata prima su una copia, come da database/README.md. Non sovrascrivere mai un campo già revisionato dal farmacista.
- I contenuti clinici (relazioni, protocolli, complementi, soglie dei segnali d'allarme) li scrive o li approva il farmacista. Tu prepari bozze `candidata`/`bozza` con la fonte, mai contenuti approvati.
- Tieni tracciabilità e registro delle decisioni (`registro_revisioni`): servono anche in vista degli obblighi dell'AI Act.

## 5. Lavoro per fasi

Quattro fasi. Una fase si chiude solo quando il suo criterio di uscita è misurato; riporta il numero nel resoconto.

### Fase 1 · Contenuti e schema (settimane 1–2)

1. Applica la migrazione 006 al catalogo operativo dopo backup e prova su copia. Aggiorna `catalog_setup.py check` perché verifichi le nuove tabelle.
2. **Protocolli di banco**: scrivi `python -m backend.protocolli pubblica <scheda>` che legge una scheda `tipo = "protocollo"` con stato `pubblicata` e la carica in `protocolli_banco` e `protocollo_voci` (domande con il filtro che alimentano, segnali d'allarme, consigli, follow-up). Prepara in bozza i protocolli dei 5 bisogni più frequenti indicati dal farmacista (in assenza di indicazioni: raffreddore, mal di gola, dolore, stomaco, intestino).
3. **Relazioni candidate per i concetti nuovi**, partendo dai prodotti già in catalogo e con il foglio illustrativo come fonte: Tantum Verde, Golamir, Propolgemma → mal di gola; Tachipirina → febbre; LenoDiar → diarrea; Melilax → stitichezza; NeoFitoroid → emorroidi; Zovirax → herpes labiale; Fenistil → punture; Dicoflor → fermenti lattici; Supradyn Energy → stanchezza; Magnesio Notte Relax → sonno. Tutte `candidata`.
4. Collega a un concetto, sempre come `candidata` con fonte, i 26 medicinali umani scoperti e gli integratori.
5. Estendi `backend/revisione.py` con i comandi `complementi` e `protocolli`, con lo stesso flusso a un elemento alla volta.
6. **Alias**: aggiungi i tipi `uso_comune` ed `errore_asr` in `alias_prodotto` (migrazione 007) e un comando per proporli dal feedback «errore_riconoscimento»; gli alias restano da approvare.
7. **Pulizia**: usa `v_prodotti_categoria` ovunque si confronti la categoria; dopo averlo verificato rimuovi le tabelle `wiki` e `wiki_fts` (migrazione 007).
8. **Golden set**: accetta frasi reali in un file `tests/frasi_banco.jsonl` (frase, concetto atteso), scritte a mano dal farmacista senza dati del cliente, e caricale in `eval_retrieval.py`.

**Criterio di uscita:** migrazione applicata; almeno 40 relazioni rivedute; 5 protocolli pubblicati; golden set ad almeno 100 frasi con almeno l'80% riconosciuto.

### Fase 2 · Dati affidabili (settimane 3–4)

1. **Import AIFA**: `python -m backend.import_aifa` scarica e importa ogni notte, su copia e poi in operativo, l'anagrafica AIFA (`confezioni_fornitura.csv`, `PA_confezioni.csv`, `atc.csv` da drive.aifa.gov.it) e l'elenco dei farmaci carenti. Associa per codice AIC; non sovrascrivere campi revisionati; registra cosa è cambiato. Cita AIFA (licenza CC-BY 4.0) nelle schede e nel piè di pagina.
2. **Regime ed età**: valorizza `regime_fornitura`, `eta_minima_anni` e le rispettive fonti per i 100 prodotti reali dal foglio illustrativo o dalla Banca Dati Farmaci AIFA. In caso di dubbio lascia `non_verificato`.
3. **Carenze**: un prodotto carente mostra l'avviso e, solo se documentato, l'equivalente disponibile.
4. **Gestionale**: import di prezzi e giacenze da un CSV esportato; mappa delle colonne in `database/configurazione.json`; righe incomplete rifiutate e contate; riepilogo dell'import.
5. **Catalogo**: prepara l'inserimento di 20–30 articoli di parafarmaco di supporto (soluzione fisiologica, fazzoletti, termometri, cerotti, borse del ghiaccio…), dei best-seller mancanti indicati dal farmacista e dei primi `complementi_banco` candidati. Prevedi il campo immagine con fonte autorizzata (foto del produttore o banca dati con licenza); senza immagine, un'icona di categoria.
6. La pagina di diagnostica mostra data ed esito dell'ultimo import di ogni fonte.

**Criterio di uscita:** nessun prodotto con regime ignoto mostrato come proposta senza etichetta; nessun prodotto su ricetta mostrato; prezzi e giacenze aggiornati ogni notte.

### Fase 3 · Ricerca, vendita e schermo (settimane 5–7)

#### 3A · Ricerca

1. **Ammissibilità prima del ranking**: in `symptom_product_matches` e nella ricerca manuale escludi i prodotti con `regime_fornitura` in (`RR`, `RNR`, `RRL`, `vet_RR`); `non_verificato` resta visibile con l'etichetta «regime da verificare». Con un'età dichiarata e un `eta_minima_anni` superiore, escludi e mostra il motivo.
2. **Ordinamento dichiarato**: sintomi coperti tra quelli detti → approvata prima di candidata → disponibilità → forma richiesta. Ogni scheda dice perché è in quella posizione.
3. **Lessico che cresce**: `python -m backend.lessico frasi-mancate` elenca i concetti segnati «non pertinente» o «errore_riconoscimento» in `feedback_banco`.
4. **Ricerca semantica, opzionale**: dietro un flag in `database/configurazione.json` (spento di default), un indice vettoriale con `sqlite-vec` (versione fissata, è pre-v1) e un modello di embedding multilingue (BGE-M3 o equivalente) su concetti e schede, fuso con lessico e FTS5. Il vettore propone solo un **concetto**, mai un prodotto, e solo se il lessico non ha trovato nulla. Se pacchetto o modello mancano, tutto funziona come prima e la diagnostica lo segnala.
5. **Classificatore su elenco chiuso, opzionale**: per le frasi che lessico e vettori non coprono, il provider LLM già previsto in `phase_agent.py` sceglie solo tra i concetti del catalogo (o «nessuno»). Spento di default; in locale si può usare un modello europeo aperto (es. Velvet, Minerva).

#### 3B · Analisi della vendita

Crea `backend/vendita.py` con uno stato della vendita per sessione, solo in memoria:

| Campo | Contenuto |
|---|---|
| `passo` | `bisogno` → `inquadramento` → `proposta` → `complemento` → `offerta` → `chiusura` |
| `bisogni` | concetti riconosciuti con l'indizio che li ha attivati |
| `destinatario` | come oggi: solo ciò che è dichiarato |
| `domande_aperte` | dal protocollo del concetto, al massimo 3, in ordine |
| `segnali_allarme` | se presenti, il passo si ferma e lo schermo mostra «invio al medico» |
| `proposti` / `confermato` / `rifiutati` | codici prodotto con l'evento che li ha mossi |
| `complemento` | l'unico mostrato, con il motivo |
| `offerte_viste` | codici offerta |

Passaggi: `inquadramento` → `proposta` quando le domande essenziali hanno risposta o il farmacista preme «salta»; `proposta` → `complemento` solo con un prodotto **confermato dal farmacista** (non basta che il cliente lo nomini); `complemento` → `offerta` quando il complemento è accettato, rifiutato o saltato. Un «non lo voglio», una correzione o un nuovo bisogno riportano al passo giusto senza perdere ciò che resta valido. Riusa le fasi già riconosciute in conversation.py (chiarimento, ricerca, scelta, extra, chiusura) e collegale ai passi senza duplicare la logica.

Scrivi in `feedback_banco` gli eventi `mostrato`, `proposto`, `accettato`, `rifiutato`, `non_pertinente`, `errore_riconoscimento`.

#### 3C · Proposta del prodotto

- Massimo 3 opzioni, già filtrate e ordinate.
- Ogni scheda: nome, forma, principio attivo, prezzo, giacenza, fonte, stato di revisione, cautele del foglio illustrativo, e la domanda ancora aperta che potrebbe escluderla.
- Esaurito o carente: equivalente solo se documentato per quella confezione.
- Pulsante «confermo questo prodotto»: l'unico evento che apre il complemento.

#### 3D · Integratore o complemento correlato

- Si apre solo dopo la conferma del prodotto.
- Candidati, in ordine: `complementi_banco` approvati per il concetto o il prodotto confermato, poi le `relazioni_prodotti` di complemento approvate.
- Escludi ciò che collide con le esclusioni del complemento, con il destinatario dichiarato o con il carrello.
- Mostra **uno solo**: priorità più alta, disponibile; motivo in una riga scritta dal revisore, mai una promessa clinica.
- Se non c'è niente di approvato: «nessun complemento approvato per questo caso» e si passa alle offerte, senza ripieghi generici.

#### 3E · Offerte

- Si aprono in chiusura, o prima se il cliente chiede esplicitamente di prezzi o promozioni.
- `active_offers` riceve solo i codici **proposti, confermati o del complemento accettato**.
- Mantieni i criteri esistenti (prodotto, cosmetico, budget dichiarato) e aggiungi `formato_convenienza`: la confezione più grande dello stesso prodotto, se in offerta e disponibile.
- Massimo 2 offerte, con validità e disponibilità residua; scadute o esaurite non compaiono; le `demo` restano etichettate.

#### 3F · Visualizzazione al banco

Il farmacista guarda lo schermo per pochi secondi mentre parla: tutto si legge a colpo d'occhio, senza scroll durante la conversazione. Lavora su frontend/index.html, frontend/desk.js e il CSS esistente, senza framework.

| Zona | Posizione | Contenuto |
|---|---|---|
| Barra del passo | In alto, tutta la larghezza | Bisogno · Domande · Prodotto · Complemento · Offerta; tappa attiva evidenziata, motivo in una riga, pulsante «salta» |
| Trascrizione | Sinistra, circa 40% | Come oggi, con le parole che hanno attivato un bisogno evidenziate; clic → regola e fonte |
| Domande | Destra in alto | Al massimo 3 domande del protocollo; una domanda con risposta diventa una spunta con la risposta riconosciuta |
| Prodotto | Destra al centro | Fino a 3 schede compatte affiancate |
| Complemento · Offerta | Destra in basso, affiancati | Grigi finché chiusi, con la scritta di cosa li apre |

Scheda prodotto compatta, ad altezza fissa: immagine o icona di categoria; nome, forma e dosaggio; prezzo e pallino di giacenza (verde, giallo sotto soglia, grigio esaurito); etichette brevi («approvata» / «non revisionata», «regime da verificare», «età minima 16», «carente»); una riga «perché è qui»; la domanda aperta in corsivo; pulsanti «confermo» e «non pertinente». Fonte e cautele complete si aprono con un clic.

Segnali d'allarme: fascia rossa sopra le zone di destra con il segnale e «invio al medico»; prodotto, complemento e offerta diventano grigi finché il farmacista non preme «gestito».

Comportamento:

- nessun lampeggio: si aggiorna solo ciò che cambia (riusa `refreshPart`); una scheda nuova entra con un'evidenziazione breve, una ritirata sparisce con una dissolvenza;
- le schede bloccate dal farmacista restano ferme;
- tastiera: `1`–`3` confermano la scheda corrispondente, `N` «non pertinente», `S` salta il passo, `Esc` chiude i dettagli;
- leggibile da un metro: testo principale almeno 16 px, contrasto AA, ogni stato ha anche una parola o un'icona oltre al colore;
- da 1366×768 in su; sotto, le zone di destra si impilano nell'ordine dei passi.

Per il cliente, dietro un flag spento di default: scheda stampabile o QR con i consigli a voce del protocollo (cosa fare, quando tornare o andare dal medico), senza dati del cliente.

Pagina `/analisi`, con grafici semplici senza librerie esterne, solo conteggi aggregati:

- barre delle sessioni per bisogno nella settimana;
- imbuto Bisogno → Prodotto proposto → Confermato → Complemento accettato → Offerta accettata, con la percentuale persa a ogni passo;
- linea settimanale dell'accettazione del complemento;
- i 10 bisogni con più «non pertinente», con il rimando a `frasi-mancate`.

**Criterio di uscita della fase 3:** nessun prodotto su ricetta né con età incompatibile mostrato; golden set non peggiorato; ogni passo del caso raffreddore funziona da tastiera; screenshot di ogni passo a 1366×768 e 1920×1080.

### Fase 4 · Voce e prova sul campo (settimane 8–10)

1. Aggiungi Silero VAD prima del motore attuale per chiudere le frasi e tagliare il silenzio.
2. Passa al motore, dove lo consente (es. prompt iniziale di whisper.cpp), i nomi dei prodotti e dei principi attivi da `alias_prodotto` come vocabolario suggerito, rigenerato quando cambia il catalogo.
3. Prepara `tools/confronto_asr.py` che confronta Vosk, whisper.cpp (large-v3-turbo quantizzato) e Voxtral Realtime (pesi aperti, circa 9 GB) su 30 dialoghi letti dal farmacista e registrati al banco con il rumore reale. Misura: famiglia di prodotto riconosciuta, sintomo riconosciuto, latenza dalla fine della frase al pannello. Le registrazioni di prova restano fuori dal repository e non contengono clienti veri.
4. Non scegliere l'hardware prima del confronto. Riporta i risultati e lascia la scelta al farmacista.
5. Prova in turno per due settimane, con il farmacista libero di ignorare l'agente; il cruscotto `/analisi` raccoglie i numeri.

**Criterio di uscita:** famiglia di prodotto riconosciuta in almeno 7 frasi su 8, sintomo in almeno 8 su 10, latenza sotto 1,5 secondi; il farmacista tiene l'agente acceso volontariamente; complemento accettato in almeno il 15% delle proposte (soglia da rivedere con i dati della prova).

## 6. Qualità del codice (in parallelo, senza cambiare comportamento)

- Sposta da desk.py in moduli separati la logica di vendita (`backend/vendita.py`), di complemento e di offerta; desk.py resta il server e l'assemblaggio dello schermo.
- In conversation.py separa riconoscimento del bisogno, destinatario e fasi in funzioni con test propri.
- Ogni spostamento deve lasciare verdi tutti i test esistenti.
- Riduci docs/TaskState.md a stato attuale, prossimi passi e decisioni; sposta lo storico in docs/STORICO.md.

## 7. Verifica

Aggiungi `tests/test_vendita.py` senza toccare i test esistenti, che devono restare verdi:

- raffreddore per un adulto: proposta → conferma → complemento approvato → offerta sul prodotto confermato;
- stesso caso senza complementi approvati: il pannello lo dice e si passa all'offerta;
- età minima 16 e destinatario di 14 anni dichiarato: escluso con il motivo;
- prodotto `RR` nel catalogo: mai mostrato;
- il cliente nomina un prodotto ma il farmacista non conferma: niente complemento;
- «non lo voglio» dopo la conferma: si torna alla proposta e il complemento sparisce;
- segnale d'allarme: le proposte si fermano;
- offerta su un prodotto mai entrato nella conversazione: non compare;
- offerta scaduta o con disponibilità zero: non compare;
- feedback salvato senza testo né dati del cliente (controlla le colonne scritte);
- import AIFA su copia con una riga modificata: cambia solo quella; un campo revisionato non viene sovrascritto;
- CSV del gestionale con righe incomplete: rifiutate e contate;
- tastiera `1` / `N` / `S` sulle schede;
- con il flag della ricerca semantica spento o senza `sqlite-vec` installato: comportamento identico a oggi.

Rilancia `python -B tests/eval_retrieval.py` e riporta il confronto prima/dopo. Distingui sempre nel resoconto: provato con test automatici, provato nel browser, provato con voce reale, non provato.

Aggiorna docs/TaskState.md alla fine di ogni fase.

## 8. Decisioni che spettano al farmacista

Non prenderle tu: lascia un segnaposto chiaro e segnalale nel resoconto.

- chi è il revisore e quanto tempo dedica a settimana;
- i 5 bisogni più frequenti al banco e i best-seller da aggiungere;
- quale gestionale usa la farmacia e se ha un export o un'API;
- budget hardware (mini-PC con GPU sì o no), dopo il confronto della fase 4;
- abbonamento a una banca dati commerciale (es. Farmadati) o solo fonti pubbliche;
- formulazione dello scopo dichiarato, da far vedere a un consulente regolatorio prima di uscire dalla prova interna;
- se attivare la scheda stampabile o il QR per il cliente.

## 9. Fuori ambito

Nessun invio di audio o testo a servizi esterni; nessun collegamento in tempo reale al gestionale (resta l'export CSV notturno); nessuna profilazione del cliente tra una visita e l'altra; nessun contenuto clinico approvato senza il farmacista.

## Riferimenti

- Analisi dei pain point e correzioni già fatte: documento «Pharmacy-assistance · Pain point e piano di miglioramento».
- Piano e nuove soluzioni con fonti: documento «Pharmacy-assistance · Piano di miglioramento e nuove soluzioni».
- AIFA, liste dei farmaci e anagrafica: https://www.aifa.gov.it/it/liste-dei-farmaci
- sqlite-vec: https://github.com/asg017/sqlite-vec · Silero VAD: https://github.com/snakers4/silero-vad · Voxtral Realtime: https://mistral.ai/news/voxtral-transcribe-2
