# Prompt · Nuova disposizione del banco e lettura dei codici da telecamera

Lavora sul repository Pharmacy-assistance. Prima di modificare leggi AGENTS.md, docs/TaskState.md (aggiornamento del 18 novembre 2026), frontend/index.html, frontend/desk.js, frontend/desk.css, backend/desk.py (`_refresh_desk_results`, `_desk_supplements`, `_refresh_sales_view`, `action`), backend/vendita.py, backend/knowledge.py e backend/import_dati.py.

Lancia subito `python -B -m unittest discover -s tests -q` (oggi 68 test verdi) e annota il risultato come base.

## Obiettivo

Lo schermo deve mostrare solo ciò che serve mentre si parla col cliente: **farmaci a sinistra, integratori collegati al centro, carrello a destra**. La trascrizione scende in una striscia orizzontale in basso, che in futuro si potrà togliere. Tutto il resto (passi della vendita, pulsanti, totale) si compatta. In più, il farmacista può inquadrare con la telecamera il codice di una confezione per riconoscere il farmaco, registrarlo nel catalogo se manca e vedere cosa consigliare insieme.

## Regole da non violare

- Valgono tutte le regole di docs/PROMPT_COMPLETO.md: il farmacista decide; nessun prodotto su ricetta proposto da un sintomo; integratori solo da relazioni documentate; offerte solo su prodotti già nella conversazione; feedback anonimo.
- La telecamera si accende solo quando il farmacista preme il pulsante e si spegne da sola dopo la lettura o dopo 30 secondi. Le immagini restano nel browser: nessun fotogramma viene salvato, inviato al server o registrato nei log; al server arriva solo il testo del codice letto.
- Un prodotto aggiunto dalla scansione entra nel catalogo con fonte e stato «da verificare». Non diventa proponibile da un sintomo finché il farmacista non lo rivede.
- Nessuna libreria da CDN: la pagina ha una CSP `default-src 'self'`. Ogni libreria va copiata in `frontend/vendor/` con licenza e versione annotate.

## 1. Disposizione dello schermo

### Intestazione compatta (una sola riga)

- A sinistra il titolo «Sales Agents» e, **nello stesso rigo**, i passi della vendita in forma compatta: `Bisogno › Domande › Prodotto › Complemento › Offerta`, con il passo attivo evidenziato e il motivo in una riga sola, troncata con puntini (testo completo nel `title`). Elimina il blocco separato `#sales-steps` che oggi occupa una riga intera.
- A destra i pulsanti in formato piccolo (altezza circa 30 px, testo 0,8 rem): «In ascolto» / «Termina» / «Azzera», «Scansiona» (nuovo, vedi sezione 3) e «Impostazioni» come icona con etichetta accessibile.
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

## 3. Lettura dei codici da telecamera

### Cosa leggere

Le confezioni possono avere codici diversi; la funzione deve accettarli tutti e lasciare al backend la decisione:

- QR code;
- GS1 DataMatrix (contiene GTIN, lotto e scadenza; usa solo il GTIN);
- codici a barre lineari: EAN-13 e Code 39 (usato per il codice AIC).

Verifica sulle confezioni reali della farmacia quali codici sono presenti e documenta nel TaskState cosa è stato provato davvero.

### Frontend

- Pulsante «Scansiona» nell'intestazione e scorciatoia `Q`. Apre un piccolo riquadro sopra la colonna Farmaci con l'anteprima della telecamera (`getUserMedia`, telecamera posteriore se esiste) e il pulsante «Chiudi».
- Decodifica in `frontend/scanner.js`: usa `BarcodeDetector` se il browser lo supporta per i formati richiesti, altrimenti una libreria locale in `frontend/vendor/` (es. ZXing per JavaScript, licenza Apache-2.0) che legge QR, DataMatrix, EAN-13 e Code 39.
- Alla prima lettura valida: suono breve facoltativo, telecamera spenta, testo del codice inviato a `POST /api/scansione` con l'id di sessione. Nessuna immagine viene inviata.
- Se la telecamera non c'è o il permesso è negato, il riquadro lo dice e offre un campo per digitare il codice (anche da lettore di codici USB, che si comporta come una tastiera).

### Backend

Nuovo modulo `backend/scansione.py`:

1. `parse_code(text)` riconosce e normalizza:
   - AIC a 9 cifre (anche con prefisso «A» del Code 39);
   - EAN-13 e GTIN-14 dal DataMatrix GS1 (Application Identifier `01`), con verifica della cifra di controllo;
   - QR con URL o testo: estrae un AIC o un GTIN se presenti, altrimenti restituisce «codice non riconosciuto».
2. `resolve(code, catalog)` cerca, in ordine:
   1. prodotto del catalogo con `id_regolatorio` = AIC, oppure con un alias di tipo `codice_pubblico` uguale a EAN/GTIN;
   2. se manca, la riga dell'anagrafica AIFA già scaricata da `import_dati` (`dati/aifa/confezioni.csv`): denominazione, titolare, ATC, principio attivo, regime di fornitura.
3. `register(aifa_row, catalog)`: se il prodotto non è in catalogo ma è nell'anagrafica AIFA, lo inserisce con:
   - codice nuovo `SCAN-<AIC>`, nome e forma dalla denominazione AIFA, `id_regolatorio` = AIC, `atc`, `regime_fornitura` dalla fornitura AIFA, fonte `SRC-AIFA-ANAGRAFICA`;
   - `stato_revisione = 'da_verificare'` (o il valore equivalente già ammesso dallo schema; se serve, migrazione 008), nessun prezzo né giacenza inventati;
   - scheda wiki in bozza generata da `catalog_wiki.py` con i soli dati AIFA;
   - riga in `registro_revisioni` e in `registro_import` (fonte `scansione`).
   Se il codice non è né in catalogo né nell'anagrafica, non inserisce nulla e propone «Aggiungi a mano» con i campi minimi, che il farmacista compila.
4. `advice_for(code, catalog)` restituisce cosa si può consigliare con quel farmaco, solo da dati documentati:
   - concetti collegati al prodotto (relazioni con fonte) e relative cautele ed età minima;
   - integratori e complementi collegati, con lo stesso ordine di probabilità della sezione 2;
   - offerte attive su quel prodotto o sulle sue varianti documentate;
   - il protocollo di banco del concetto, se pubblicato (domande e consigli).
   Se il prodotto è nuovo da scansione e non ha ancora relazioni, lo dice: «Nessun abbinamento documentato: da completare in revisione».
5. Endpoint `POST /api/scansione` in desk.py, con gli stessi controlli di origine, sessione e versione delle altre azioni. Il prodotto letto diventa il farmaco **selezionato** nella colonna sinistra (come se fosse stato nominato dal cliente, con evidenza «scansione»), e la colonna Integratori si aggiorna di conseguenza. Non viene confermato né messo nel carrello in automatico.
6. Diagnostica: «Telecamera» (disponibile / permesso negato / assente) e ultimo esito della scansione, senza immagini né codici completi nei log.

## 4. Verifica

Test nuovi, senza modificare quelli esistenti:

- `parse_code`: AIC a 9 cifre con e senza «A», EAN-13 valido e con cifra di controllo errata, DataMatrix GS1 con `01` + lotto + scadenza, QR con URL contenente un AIC, testo libero → non riconosciuto.
- `resolve` / `register`: prodotto già in catalogo → nessun inserimento; prodotto solo in AIFA (CSV di prova) → inserito come «da verificare» con fonte, senza prezzo, e **non** proposto da un sintomo; codice sconosciuto → nessun inserimento.
- `advice_for`: con relazioni e complementi approvati restituisce gli integratori nell'ordine dei livelli; senza relazioni restituisce il messaggio esplicito.
- `linked_supplements`: un integratore con abbinamento approvato al farmaco sta davanti a uno legato solo al concetto; integratori nel carrello o esauriti esclusi.
- Endpoint `/api/scansione`: origine estranea rifiutata; sessione scaduta rifiutata; il prodotto letto risulta selezionato e non confermato.
- Snapshot senza campi immagine o frame.

Verifica nel browser (Chrome headless come nell'aggiornamento del 18 novembre, con trascrizione iniettata), screenshot a 1366×768 e 1920×1080 di:

1. tre colonne con trascrizione in basso;
2. clic su un farmaco con integratori evidenziati;
3. trascrizione ridotta e con `mostra_trascrizione: false`;
4. riquadro di scansione aperto (telecamera simulata con il flag Chrome `--use-fake-device-for-media-stream` e un'immagine di un QR di prova) e risultato della scansione.

Controlla: a 1366×768 almeno 5 schede farmaco visibili senza scorrere; intestazione su una riga; nessun segnaposto «Si apre…» sullo schermo.

Distingui nel resoconto ciò che è provato con test automatici, nel browser, con telecamera reale e confezioni reali, oppure non provato. Aggiorna docs/TaskState.md con un nuovo aggiornamento in testa nello stile esistente e i requisiti R45 (disposizione a tre colonne), R46 (integratori evidenziati), R47 (scansione dei codici).

## Fuori ambito

Nessun invio di immagini o codici a servizi esterni; nessuna lettura della ricetta o di dati del paziente dalla telecamera; nessuna modifica automatica del carrello dalla scansione; nessuna rimozione definitiva della trascrizione (solo nascosta da impostazione).
