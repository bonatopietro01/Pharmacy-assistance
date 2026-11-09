# Catalogo SQLite

Il catalogo operativo si trova in `farmacia.sqlite3`. La versione 3 contiene 12 prodotti, 2 relazioni e 2 offerte dimostrative. La migrazione `004_catalogo_v4.sql` conserva gli identificativi e i valori dei record demo, aggiunge la provenienza e permette ai prodotti reali di avere prezzo e quantità `NULL` finché la farmacia non fornisce dati autorizzati.

## Schema v4

- `prodotti.prezzo_cent` è il prezzo al banco; `prezzo_riferimento_cent` è un eventuale prezzo pubblico separato. Ogni valore commerciale richiede una fonte e una data.
- `prodotti.quantita` indica la disponibilità nella farmacia solo se valorizzata da una fonte della farmacia. Il numero `NULL` significa che la disponibilità è sconosciuta. I record reali importati dal seed non ricevono prezzi o scorte demo.
- `principi_attivi` e `prodotto_principi_attivi` modellano uno o più principi attivi per prodotto e mantengono le quantità per unità quando documentate.
- `componenti_integratore` e `prodotto_componenti_integratore` mantengono separati gli ingredienti dichiarati in etichetta per gli integratori: non sono classificati come principi attivi di medicinali.
- `alias_prodotto` contiene nomi alternativi di ricerca. Un alias non equivale a un generico o a un prodotto equivalente.
- `fonti` e `prodotto_fonti` conservano URL, titolo, ente, versione/data e l'affermazione supportata dalla fonte. Le fonti AIFA/Gazzetta storiche annidate nel dataset sono registrate separatamente: identificativi regolatori e composizioni storici restano `candidata`; non attestano lo stato corrente. `dato_storico` indica soltanto che la fonte è storica.
- `relazioni_prodotti` distingue relazioni demo, candidate, approvate e respinte. Il backend esclude dal banco le relazioni cliniche senza stato approvato e farmacista revisore.
- `concetti` e `relazioni_concetto_prodotto` separano i temi/sintomi dalle relazioni tra prodotti. Le righe `indicazione_etichetta` con stato `candidata` possono comparire nella postazione come corrispondenze informative dopo una menzione stabile del sintomo, con fonte e stato di revisione visibili. Non sono consigli approvati, possono essere ordinate per copertura documentale dei sintomi e non scattano da una parola provvisoria.

Gli stati regolatori, la prova di commercializzazione e la disponibilità nella singola farmacia sono campi distinti. Le relazioni di equivalenza richiedono fonti coerenti con principio attivo, quantità, forma, via e stato regolatorio. Un nome simile o la co-occorrenza in una fonte commerciale non provano un'equivalenza o una relazione clinica.

## Fonti ammesse e dati mancanti

Per l'identità, composizione e stato dei medicinali, consultare la Banca Dati dei Farmaci e i documenti ufficiali AIFA. Gli RCP e fogli illustrativi sono fonti ufficiali e aggiornabili nel tempo ([AIFA: RCP e Foglio Illustrativo](https://www.aifa.gov.it/riassunto-caratteristiche-e-foglio-illustrativo), [Banca Dati AIFA](https://medicinali.aifa.gov.it/it/)). L'elenco aperto AIFA descrive le confezioni autorizzate; l'autorizzazione non prova da sola la commercializzazione corrente.

Per gli integratori, il Registro nazionale del Ministero della Salute identifica le notifiche, ma la stessa amministrazione specifica che l'iscrizione non è approvazione, conformità attestata o autorizzazione ([Ministero della Salute: Registro degli integratori](https://www.salute.gov.it/new/it/tema/alimenti-fini-medici-speciali-ed-integratori/registro-degli-integratori-alimentari/)). Usare anche una pagina corrente del titolare/produttore per documentare la presenza del prodotto sul mercato. Per dispositivi e altri articoli usare fonti del produttore o fonti regolatorie pertinenti alla classe del dispositivo.

Quando una fonte manca, è datata o confligge con un'altra, mantenere il dato `NULL` o lo stato `non_verificato` e registrare la discrepanza nella ricerca delle fonti. La presenza di un AIC storico non rende verificati l'AIC corrente, l'autorizzazione o il regime di fornitura: lo stato regolatorio rimane `non_verificato` finché una fonte AIFA individuale e corrente non supporta esplicitamente la claim. Non trasformare autorizzazione in disponibilità; non dedurre prezzo o stock dal sito di un produttore o di un rivenditore. Il gestionale della farmacia non è collegato.

## Migrazione e seed ripetibile

Fare una copia del database prima di applicare una migrazione. Eseguire prima la migrazione sulla copia e controllare schema, integrità e chiavi esterne. Lo script accetta soltanto il passaggio v3→v4; se è già v4 lo lascia invariato.

```powershell
$salesPython = 'C:\Users\bonat\AppData\Local\Python\pythoncore-3.14-64\python.exe'
Copy-Item database\farmacia.sqlite3 database\farmacia-pre-v4.sqlite3
& $salesPython backend\catalog_setup.py migrate --catalog database\farmacia-pre-v4.sqlite3
& $salesPython backend\catalog_setup.py seed --catalog database\farmacia-pre-v4.sqlite3 --seed database\catalogo-reale.json
& $salesPython backend\catalog_setup.py check --catalog database\farmacia-pre-v4.sqlite3
```

Il comando `seed` è ripetibile: aggiorna i codici reali già presenti, non sovrascrive i record demo, deduplica fonti e principi attivi, riallinea alias e principi attivi del seed e rifiuta prezzi o scorte valorizzati senza fonte della farmacia. I nomi commerciali e la composizione restano distinti dallo stato di revisione clinica. Tutti i record importati sono `da_revisionare`; l'importazione non approva associazioni o consigli.

Solo dopo aver verificato la copia si può applicare il medesimo comando al catalogo operativo locale. Il backup della base in uso va conservato fino al completamento del controllo. Lo script non esegue backup automatici e non legge o aggiorna sistemi esterni.

## Relazioni con la wiki

Le schede editoriali restano in `wiki/schede/`. I codici del catalogo sono il riferimento stabile; nomi e alias consentono la ricerca. Aggiornare la wiki solo con fatti e relazioni che abbiano una fonte adeguata e stato di revisione esplicito. Il seed `collegamenti-sintomo.json` contiene collegamenti documentali candidati per raffreddore, congestione nasale e tosse, collegati a fonti ufficiali del prodotto. Il loro stato resta `candidata`: la postazione li distingue chiaramente dalle relazioni revisionate e il farmacista verifica destinatario, avvertenze e indicazione prima di una proposta. Non si derivano associazioni da co-occorrenze o dalle vendite.

Il comando seguente carica o riallinea in modo idempotente concetti e collegamenti nel catalogo v4. Richiede che ogni prodotto esista nel catalogo e che la fonte sia una pagina ufficiale collegata al prodotto per identita' o commercializzazione. La claim di fonte `associazione_clinica` deve essere gia' `verificata` o viene inserita come tale solo quando manca; registra che la pagina ufficiale documenta l'indicazione. La relazione concetto-prodotto rimane `candidata`: la claim verificata non approva la relazione e non trasforma il match informativo in consiglio. Una claim esistente con stato `demo`, `candidata` o `respinta` fa fallire e annullare l'intera transazione del seed; il seed non converte mai uno stato esistente. I collegamenti gia' approvati o respinti non vengono declassati o riattivati dal seed.

```powershell
$salesPython = 'C:\Users\bonat\AppData\Local\Python\pythoncore-3.14-64\python.exe'
& $salesPython backend\catalog_setup.py seed-symptoms --catalog database\farmacia.sqlite3 --symptom-seed database\collegamenti-sintomo.json
& $salesPython backend\catalog_setup.py check --catalog database\farmacia.sqlite3
```

Prima di applicare il seed operativo, fare una copia del file SQLite e verificarla. Il seed modifica solo le tabelle `fonti` (quando una fonte ufficiale manca), `concetti`, `relazioni_concetto_prodotto` e `prodotto_fonti`; non cambia prodotti, prezzi, scorte, alias o altre relazioni.

## Confezioni documentate

`confezioni.json` è un elenco di gruppi espliciti. Ogni gruppo contiene `source_id` (fonte ufficiale con identità verificata per ogni SKU) e `packages` (oggetto con codice di catalogo → etichetta della confezione). Il banco espone il gruppo soltanto se tutti i codici sono recuperabili e forma, via, concentrazione e ingredienti documentati coincidono. Prezzo e disponibilità vengono letti per codice. Il registro operativo è vuoto perché il seed attuale accorpa le differenze di quantità nello stesso record e non fornisce uno SKU per ciascuna confezione.

`classificazioni.json` è un oggetto indicizzato per codice di catalogo. Ogni record dichiara `classification` (`generico` o `marca`) e `source_id`. Inserire una voce solo se la fonte attesta esplicitamente la classificazione e ha una claim di identità verificata per lo stesso codice. Il registro iniziale è vuoto. Nome e principio attivo da soli non determinano la classificazione.

## Funzioni demo preesistenti

La tabella `offerte` e la coda `reintegro.sqlite3` conservano le funzioni dimostrative. Il calcolo di reintegro considera solo quantità note e i relativi avvisi vengono filtrati sul prodotto visibile. I prodotti reali senza una fonte di scorte rimangono fuori dalla coda di reintegro.

## Listino, scorte e promozioni di prova

`python -m backend.demo_inventory --catalog database/farmacia.sqlite3 --date 2026-11-08 --wiki wiki/LISTINO_DEMO.md` applica lo scenario esplicito di prova. Eseguire con il banco chiuso e dopo il backup. Per ogni SKU idoneo, il modulo inserisce valori sintetici con fonte `SRC-SALES-DEMOBANCO-20261108`. Prezzi e scorte con una fonte diversa restano invariati. Le tre promozioni demo illustrano rispettivamente un’offerta valida, una scaduta e una esaurita. Il listino Markdown deriva dai valori SQLite etichettati dalla stessa fonte.
