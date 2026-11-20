# Prompt · Nuova disposizione del banco e pagina «Scheda farmaco»

Lavora sul repository Pharmacy-assistance. Prima di modificare leggi AGENTS.md, docs/TaskState.md (aggiornamento del 18 novembre 2026), frontend/index.html, frontend/desk.js, frontend/desk.css, backend/desk.py (`_refresh_desk_results`, `_desk_supplements`, `_refresh_sales_view`, `action`), backend/vendita.py, backend/knowledge.py e backend/import_dati.py.

Lancia subito `python -B -m unittest discover -s tests -q` (oggi 68 test verdi) e annota il risultato come base.

## Obiettivo

Lo schermo deve mostrare solo ciò che serve mentre si parla col cliente: **farmaci a sinistra, integratori collegati al centro, carrello a destra**. La trascrizione scende in una striscia orizzontale in basso, che in futuro si potrà togliere. Tutto il resto (passi della vendita, pulsanti, totale) si compatta. Tutto ciò che riguarda un singolo farmaco fuori dalla conversazione va in una **pagina separata, «Scheda farmaco»** (`/farmaco`). Lì il farmacista legge il codice della confezione con la telecamera, consulta tutte le informazioni, aggiorna i dati e fa domande sul farmaco. Il banco non mostra nulla di tutto questo: ha solo un collegamento alla pagina.

## Regole da non violare

- Valgono tutte le regole di docs/PROMPT_COMPLETO.md: il farmacista decide; nessun prodotto su ricetta proposto da un sintomo; integratori solo da relazioni documentate; offerte solo su prodotti già nella conversazione; feedback anonimo.
- La telecamera si usa solo nella pagina Scheda farmaco, si accende solo quando il farmacista preme il pulsante e si spegne da sola dopo la lettura o dopo 30 secondi. Le immagini restano nel browser: nessun fotogramma viene salvato, inviato al server o registrato nei log; al server arriva solo il testo del codice letto.
- Un prodotto aggiunto dalla scansione entra nel catalogo con fonte e stato «da verificare». Non diventa proponibile da un sintomo finché il farmacista non lo rivede.
- Nessuna libreria da CDN: la pagina ha una CSP `default-src 'self'`. Ogni libreria va copiata in `frontend/vendor/` con licenza e versione annotate.

## 1. Disposizione dello schermo

### Intestazione compatta (una sola riga)

- A sinistra il titolo «Sales Agents» e, **nello stesso rigo**, i passi della vendita in forma compatta: `Bisogno › Domande › Prodotto › Complemento › Offerta`, con il passo attivo evidenziato e il motivo in una riga sola, troncata con puntini (testo completo nel `title`). Elimina il blocco separato `#sales-steps` che oggi occupa una riga intera.
- A destra i pulsanti in formato piccolo (altezza circa 30 px, testo 0,8 rem): «In ascolto» / «Termina» / «Azzera», il collegamento «Scheda farmaco» (apre `/farmaco` in una nuova scheda del browser, vedi sezione 3) e «Impostazioni» come icona con etichetta accessibile.
- Il pulsante «Carrello · 2 · 18,30 €» esce dall'intestazione: numero di pezzi e totale vanno nell'intestazione della colonna Carrello.
- «Salta» compare accanto ai passi solo quando il passo si può saltare.

### Corpo su tre colonne

| Colonna | Larghezza indicativa | Contenuto |
|---|---|---|
| Farmaci | 40% | Domande da fare (se ci sono), poi le schede dei medicinali e dei dispositivi proposti o nominati |
| Integratori collegati | 30% | Gli integratori legati al bisogno o al farmaco selezionato, con evidenziati i più probabili |
| Carrello | 30% | La colonna di vendita che c'è già oggi (carrello, prezzi, offerte), con totale e numero di pezzi nell'intestazione |

- Elimina del tutto i riquadri «Complemento · Si apre dopo la conferma del prodotto» e «Offerta · Si apre alla chiusura, sui prodotti già proposti»: nessun segnaposto vuoto sullo schermo.
- Le offerte, quando ci sono, compaiono nella colonna Carrello sopra l'elenco degli articoli, al massimo 2.
- «Da dire al cliente» (consigli del protocollo) resta in fondo alla colonna Carrello, compatto, e compare solo se c'è contenuto.
- La fascia rossa dei segnali d'allarme resta sopra le tre colonne e le blocca come oggi.
- Ogni colonna scorre per conto suo; la pagina non scorre.

### Trascrizione

- Striscia orizzontale sotto le tre colonne, alta 2–3 righe (circa 5 rem), con le parole che hanno attivato un bisogno evidenziate come oggi.
- Un pulsante la riduce a una riga; l'impostazione si ricorda nel browser (localStorage, con try/catch).
- Aggiungi in `database/configurazione.json` la chiave `"mostra_trascrizione": true` (conservata da `PRESERVED_CONFIG_KEYS`): con `false` la striscia sparisce e le colonne prendono tutta l'altezza. Così in futuro si toglie senza toccare il codice.

### Sotto i 1200 px

Le colonne si impilano nell'ordine Farmaci → Integratori → Carrello; la trascrizione resta in fondo.

## 2. Schede compatte e integratori evidenziati

### Scheda farmaco compatta

Obiettivo: almeno 5 schede visibili senza scorrere a 1366×768.

- Altezza massima circa 64 px su due righe:
  - riga 1: numero (1–3 per la tastiera), miniatura 40×40 o icona di categoria, nome e forma in grassetto (una riga, troncata), prezzo a destra;
  - riga 2: pallino di giacenza, al massimo 3 etichette brevi (es. «non revisionata», «età min. 16», «carente»), poi i pulsanti icona «Conferma» (✓), «Aggiungi» (+) e «Fonti» (i), da 28 px, con `aria-label` e `title`.
- «Perché è qui», cautele, varianti e «Non pertinente» si aprono con un clic sulla scheda (dettaglio a fisarmonica), non sono sempre visibili.
- I sintomi coperti diventano un'etichetta sola (es. «copre 2 su 3»), con l'elenco nel dettaglio.
- Rimuovi bordi e spaziature doppie: una riga separatrice sottile tra le schede, padding verticale 4 px.

### Colonna Integratori collegati

Il backend calcola, per ogni farmaco visibile, gli integratori collegati e il loro punteggio; il frontend mostra la colonna e la evidenziazione.

1. In `backend/vendita.py` aggiungi `linked_supplements(state, catalog)` che restituisce gli integratori candidati con, per ciascuno, `linked_to` = elenco di `{code_farmaco, livello, motivo}`. Livelli in ordine di probabilità:
   1. abbinamento **approvato** tra quel farmaco e l'integratore (`relazioni_prodotti` di complemento approvato, oppure `complementi_banco` approvato con `prodotto_origine` = farmaco);
   2. complemento di banco approvato per il **concetto** del farmaco;
   3. integratore collegato con fonte allo **stesso concetto** (relazione `candidata` o `approvata` in `relazioni_concetto_prodotto`), etichettato «non revisionato» se candidato;
   4. nessun collegamento: non compare.
   Escludi integratori già nel carrello, esauriti o in conflitto con le esclusioni dichiarate o con il destinatario. Non inventare collegamenti: se non c'è un record, l'integratore non c'è.
2. Esponi il risultato nello snapshot (`state["desk_results"]["linked_supplements"]`), aggiornato a ogni valutazione e dopo ogni azione.
3. Nel frontend la colonna mostra tutti gli integratori collegati ai farmaci visibili, compatti come le schede farmaco.
4. **Clic su un farmaco** a sinistra (o tasto `1`–`3`): la scheda si seleziona e nella colonna centrale gli integratori collegati a quel farmaco salgono in cima, evidenziati con bordo colorato e l'etichetta del livello («abbinamento approvato», «per lo stesso bisogno»); gli altri restano visibili ma attenuati. Secondo clic o `Esc` toglie la selezione.
5. Selezionare non vuol dire confermare: la conferma resta il pulsante ✓. Dopo la conferma, l'integratore più probabile resta evidenziato come proposta da fare al cliente (sostituisce il vecchio riquadro «Complemento»), con «Accettato · al carrello» e «Rifiutato».
6. Registra in `feedback_banco` gli eventi `mostrato` / `accettato` / `rifiutato` dell'integratore evidenziato, come oggi per il complemento.

## 3. Pagina «Scheda farmaco» (`/farmaco`)

Una pagina a parte, aperta in un'altra scheda del browser, per lavorare su un farmaco alla volta: **trovarlo, leggerlo, aggiornarlo, chiedere**. Non tocca la sessione d'ascolto, salvo il pulsante esplicito «Mostra al banco».

### Struttura della pagina

| Zona | Contenuto |
|---|---|
| In alto | Barra di ricerca unica: campo di testo (nome, principio attivo, AIC, EAN; funziona anche con un lettore di codici USB, che scrive come una tastiera) e pulsante «Scansiona» per la telecamera |
| Colonna sinistra (60%) | La scheda del farmaco trovato, in schede (tab): **Informazioni** · **Consigli** · **Aggiorna** · **Storico** |
| Colonna destra (40%) | **Chiedi sul farmaco**: domande in linguaggio naturale con risposte dalle fonti del farmaco |

Dalla pagina si torna al banco con un collegamento; «Mostra al banco» rende il farmaco il prodotto selezionato nella sessione attiva, come se il cliente l'avesse nominato (evidenza «scheda farmaco»). Non lo conferma e non lo mette nel carrello.

### 3.1 Trovare il farmaco: ricerca e scansione

**Codici da leggere.** Le confezioni possono avere codici diversi; la pagina li accetta tutti e lascia la decisione al backend:

- QR code;
- GS1 DataMatrix (contiene GTIN, lotto e scadenza; si usa solo il GTIN);
- codici a barre lineari EAN-13 e Code 39 (usato per il codice AIC).

Verifica sulle confezioni reali della farmacia quali codici sono presenti e documenta nel TaskState cosa è stato provato davvero.

**Telecamera.**

- «Scansiona» (o tasto `Q`) apre l'anteprima (`getUserMedia`, telecamera posteriore se esiste) con «Chiudi».
- Decodifica in `frontend/scanner.js`: `BarcodeDetector` se il browser lo supporta per i formati richiesti, altrimenti una libreria locale in `frontend/vendor/` (es. ZXing per JavaScript, licenza Apache-2.0) per QR, DataMatrix, EAN-13 e Code 39.
- Alla prima lettura valida la telecamera si spegne e al server arriva solo il testo del codice (`POST /api/farmaco/codice`). Nessuna immagine viene inviata o salvata. Spegnimento automatico dopo 30 secondi senza lettura.
- Senza telecamera o con permesso negato, la pagina lo dice e resta il campo di testo.

**Backend** — nuovo modulo `backend/scheda_farmaco.py`:

1. `parse_code(text)` riconosce e normalizza AIC a 9 cifre (anche con prefisso «A» del Code 39), EAN-13 e GTIN-14 dal DataMatrix GS1 (Application Identifier `01`) con verifica della cifra di controllo, QR con URL o testo da cui estrae AIC o GTIN; altrimenti «codice non riconosciuto».
2. `find(query, catalog)` cerca nel catalogo per codice (`id_regolatorio`, alias `codice_pubblico`), poi per nome e principio attivo (riusa la ricerca di `knowledge.py`); se ci sono più risultati restituisce un elenco breve da cui scegliere.
3. Se il codice non è in catalogo, cerca nell'anagrafica AIFA già scaricata da `import_dati` (`dati/aifa/confezioni.csv`) e propone «Aggiungi al catalogo» con l'anteprima dei dati AIFA (denominazione, titolare, ATC, principio attivo, regime di fornitura). Il farmacista conferma.
4. `register(aifa_row, catalog, revisore)` inserisce il prodotto con codice `SCAN-<AIC>`, nome e forma dalla denominazione AIFA, `id_regolatorio`, `atc`, `regime_fornitura` e fonte `SRC-AIFA-ANAGRAFICA`, stato «da verificare» (se lo schema non ha un valore adatto, migrazione 008), nessun prezzo né giacenza inventati; genera la scheda wiki in bozza con `catalog_wiki.py`; scrive `registro_revisioni` e `registro_import` (fonte `scheda_farmaco`). Un prodotto «da verificare» non è proponibile da un sintomo.
5. Se il codice non è né in catalogo né in AIFA: nessun inserimento automatico; la pagina offre «Aggiungi a mano» con i campi minimi (nome, categoria, forma, fonte obbligatoria).

### 3.2 Scheda «Informazioni» (sola lettura)

Tutto ciò che il sistema sa del farmaco, ogni dato con la sua fonte e data:

- identità: nome, forma, confezione, titolare, AIC/EAN, ATC, principio attivo, categoria, immagine se presente;
- ammissibilità: regime di fornitura, età minima, carenza AIFA, stato di revisione;
- vendita: prezzo, giacenza, data dell'ultimo aggiornamento e fonte (gestionale, manuale, demo);
- bisogni collegati: relazioni sintomo–prodotto con indicazione, cautele, esclusioni, stato (candidata/approvata), fonte;
- varianti documentate (altre confezioni dello stesso prodotto);
- scheda wiki collegata (testo e link).

### 3.3 Scheda «Consigli» — cosa proporre insieme

Solo da dati documentati, nello stesso ordine di probabilità della colonna Integratori del banco:

1. abbinamenti approvati con questo farmaco (`relazioni_prodotti`, `complementi_banco` con `prodotto_origine`);
2. complementi di banco approvati per i bisogni del farmaco;
3. integratori collegati con fonte agli stessi bisogni (etichetta «non revisionato» se candidati);
4. offerte attive sul farmaco o sulle sue varianti;
5. domande e consigli a voce del protocollo di banco del bisogno, se pubblicato.

Ogni voce ha un pulsante «Proponi per revisione» che crea un abbinamento **candidato** (farmaco → integratore o categoria di scaffale) con motivo e fonte obbligatori, da approvare poi con `backend/revisione.py`. Se non c'è nulla: «Nessun abbinamento documentato: puoi proporne uno».

### 3.4 Scheda «Aggiorna»

Modifiche fatte dal farmacista, ciascuna con nome del revisore (chiesto una volta per sessione della pagina e ricordato nel browser) e nota facoltativa:

| Campo | Regola |
|---|---|
| Prezzo al banco, giacenza | Fonte «manuale», data odierna; il prossimo import del gestionale li sovrascrive (scritto accanto al campo) |
| Alias (nome d'uso comune, storpiatura vocale) | Entra come `candidata` in `alias_prodotto`; approvazione con `revisione alias` |
| Regime di fornitura, età minima | Richiede una fonte (URL del foglio illustrativo o della Banca Dati Farmaci AIFA); un valore con fonte del farmacista non viene più sovrascritto dall'import AIFA |
| Immagine | Solo file caricato dal farmacista o URL del produttore, con fonte; copiata in `wiki/immagini/`, ridimensionata a 400 px |
| Stato «da verificare» → «verificato» | Solo dopo aver controllato identità e regime; abilita la proposta da sintomo |
| Relazione con un bisogno | «Proponi relazione» crea una relazione `candidata` con indicazione, cautele, esclusioni e fonte obbligatorie |

Ogni salvataggio passa da `POST /api/farmaco/aggiorna`, con controlli di origine, tipi e lunghezze come le altre API; scrive `registro_revisioni` (prima/dopo). Nessuna modifica diretta a una relazione già approvata: si propone una nuova versione candidata.

### 3.5 Scheda «Storico»

Elenco delle modifiche al farmaco da `registro_revisioni` e `registro_import` (data, campo, prima/dopo, revisore o fonte), più numero di volte proposto/accettato al banco da `feedback_banco` (solo conteggi).

### 3.6 «Chiedi sul farmaco»

Domande libere sul farmaco aperto, es. «si può dare a un bambino di 8 anni?», «c'è in un formato più grande?», «cosa abbino per la gola?», «è in carenza?».

- Risposta **solo dai dati del farmaco**: campi del catalogo, relazioni, cautele, varianti, offerte, scheda wiki e testi delle fonti già registrate. Ogni risposta cita i record e le fonti usati, con link.
- Modalità locale, sempre attiva: riconoscimento delle domande frequenti per parole chiave (età, gravidanza, dosi → rimanda al foglio illustrativo, formati, prezzo, disponibilità, carenza, abbinamenti, regime) e risposta con i campi corrispondenti; per il resto, ricerca FTS nella scheda wiki del farmaco con il brano pertinente.
- Modalità con modello, facoltativa e spenta di default: usa il provider già previsto in `phase_agent.py` (o un modello locale), passandogli **solo** i record del farmaco; istruzione di rispondere «non risulta dalle fonti registrate» quando l'informazione manca. Nessun dato del cliente entra nella domanda.
- Mai dosi personalizzate o scelte terapeutiche: per posologia la risposta rimanda al foglio illustrativo citato; per dubbi clinici, al medico.
- Le domande non vengono salvate. Se la risposta è «non risulta», la pagina propone di aggiungere l'informazione mancante dalla scheda «Aggiorna».

### Diagnostica

Aggiungi «Telecamera» (disponibile / permesso negato / assente) e l'esito dell'ultima lettura di codice, senza immagini né codici completi nei log.

## 4. Verifica

Test nuovi, senza modificare quelli esistenti:

- `parse_code`: AIC a 9 cifre con e senza «A», EAN-13 valido e con cifra di controllo errata, DataMatrix GS1 con `01` + lotto + scadenza, QR con URL contenente un AIC, testo libero → non riconosciuto.
- `find` / `register`: prodotto già in catalogo → nessun inserimento; prodotto solo in AIFA (CSV di prova) → inserito come «da verificare» solo dopo conferma, con fonte, senza prezzo, e **non** proposto da un sintomo; codice sconosciuto → nessun inserimento.
- Consigli: con relazioni e complementi approvati restituisce gli integratori nell'ordine dei livelli; senza relazioni restituisce il messaggio esplicito; «Proponi per revisione» crea solo righe candidate.
- Aggiorna: prezzo e giacenza manuali registrati con fonte e revisore; regime senza fonte rifiutato; regime con fonte del farmacista non sovrascritto dall'import AIFA; ogni salvataggio in `registro_revisioni`; input troppo lunghi o di tipo errato rifiutati.
- Chiedi: domanda sull'età → risposta con l'età minima e la sua fonte; domanda sulla dose → rimando al foglio illustrativo, nessun numero; domanda su dati assenti → «non risulta dalle fonti registrate»; modalità modello spenta di default.
- «Mostra al banco»: il prodotto risulta selezionato nella sessione attiva e non confermato; senza sessione attiva il pulsante è disattivato.
- `linked_supplements`: un integratore con abbinamento approvato al farmaco sta davanti a uno legato solo al concetto; integratori nel carrello o esauriti esclusi.
- Endpoint `/api/farmaco/*`: origine estranea rifiutata; nessuna immagine o frame accettato dal server.
- Snapshot senza campi immagine o frame.

Verifica nel browser (Chrome headless come nell'aggiornamento del 18 novembre, con trascrizione iniettata), screenshot a 1366×768 e 1920×1080 di:

1. tre colonne con trascrizione in basso;
2. clic su un farmaco con integratori evidenziati;
3. trascrizione ridotta e con `mostra_trascrizione: false`;
4. pagina `/farmaco`: ricerca per nome, scansione con telecamera simulata (flag Chrome `--use-fake-device-for-media-stream` e `--use-file-for-fake-video-capture` con un QR di prova), le quattro schede e una domanda in «Chiedi sul farmaco».

Controlla: a 1366×768 almeno 5 schede farmaco visibili senza scorrere; intestazione su una riga; nessun segnaposto «Si apre…» sul banco; nessun elemento di scansione o modifica nella pagina del banco.

Distingui nel resoconto ciò che è provato con test automatici, nel browser, con telecamera reale e confezioni reali, oppure non provato. Aggiorna docs/TaskState.md con un nuovo aggiornamento in testa nello stile esistente e i requisiti R45 (disposizione a tre colonne), R46 (integratori evidenziati), R47 (pagina Scheda farmaco: scansione, consultazione, aggiornamento, domande).

## Fuori ambito

Nessun invio di immagini o codici a servizi esterni; nessuna lettura della ricetta o di dati del paziente dalla telecamera; nessuna modifica automatica del carrello o della conferma dalla pagina Scheda farmaco; nessuna approvazione clinica dalla pagina (solo proposte candidate); nessuna rimozione definitiva della trascrizione (solo nascosta da impostazione).
