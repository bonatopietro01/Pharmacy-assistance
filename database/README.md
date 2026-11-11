# Catalogo SQLite

Il catalogo operativo si trova in `farmacia.sqlite3`. La versione corrente è lo schema v5: conserva i record e le relazioni esistenti e aggiunge un ambito specie per separare i medicinali umani da quelli veterinari. La migrazione `004_catalogo_v4.sql` aggiungeva la provenienza e permetteva ai prodotti reali di avere prezzo e quantità `NULL`; `005_specie_destinazione.sql` aggiunge il solo campo specie e porta i medicinali umani esistenti a `umana`.

## Schema v5

- `prodotti.prezzo_cent` è il prezzo al banco; `prezzo_riferimento_cent` è un eventuale prezzo pubblico separato. Ogni valore commerciale richiede una fonte e una data.
- `prodotti.quantita` indica la disponibilità nella farmacia solo se valorizzata da una fonte della farmacia. Il numero `NULL` significa che la disponibilità è sconosciuta. I record reali importati dal seed non ricevono prezzi o scorte demo.
- `principi_attivi` e `prodotto_principi_attivi` modellano uno o più principi attivi per prodotto e mantengono le quantità per unità quando documentate.
- `componenti_integratore` e `prodotto_componenti_integratore` mantengono separati gli ingredienti dichiarati in etichetta per gli integratori: non sono classificati come principi attivi di medicinali.
- `alias_prodotto` contiene nomi alternativi di ricerca. Un alias non equivale a un generico o a un prodotto equivalente.
- `fonti` e `prodotto_fonti` conservano URL, titolo, ente, versione/data e l'affermazione supportata dalla fonte. Le fonti AIFA/Gazzetta storiche annidate nel dataset sono registrate separatamente: identificativi regolatori e composizioni storici restano `candidata`; non attestano lo stato corrente. `dato_storico` indica soltanto che la fonte è storica.
- `relazioni_prodotti` distingue relazioni demo, candidate, approvate e respinte. Il backend esclude dal banco le relazioni cliniche senza stato approvato e farmacista revisore.
- `concetti` e `relazioni_concetto_prodotto` separano i temi/sintomi dalle relazioni tra prodotti. Le righe `indicazione_etichetta` con stato `candidata` possono comparire nella postazione come corrispondenze informative dopo una menzione stabile del sintomo, con fonte e stato di revisione visibili. Non sono consigli approvati, possono essere ordinate per copertura documentale dei sintomi e non scattano da una parola provvisoria.
- `prodotti.specie_destinazione` vale `umana`, `cane`, `gatto` o `cane_gatto`. I record veterinari richiedono una specie esplicita. La conversazione non recupera tali prodotti senza specie animale dichiarata e corrispondente; non esistono dosaggi o sostituzioni automatiche.

Gli stati regolatori, la prova di commercializzazione e la disponibilità nella singola farmacia sono campi distinti. Le relazioni di equivalenza richiedono fonti coerenti con principio attivo, quantità, forma, via e stato regolatorio. Un nome simile o la co-occorrenza in una fonte commerciale non provano un'equivalenza o una relazione clinica.

## Fonti ammesse e dati mancanti

Per l'identità, composizione e stato dei medicinali, consultare la Banca Dati dei Farmaci e i documenti ufficiali AIFA. Gli RCP e fogli illustrativi sono fonti ufficiali e aggiornabili nel tempo ([AIFA: RCP e Foglio Illustrativo](https://www.aifa.gov.it/riassunto-caratteristiche-e-foglio-illustrativo), [Banca Dati AIFA](https://medicinali.aifa.gov.it/it/)). L'elenco aperto AIFA descrive le confezioni autorizzate; l'autorizzazione non prova da sola la commercializzazione corrente.

Per gli integratori, il Registro nazionale del Ministero della Salute identifica le notifiche, ma la stessa amministrazione specifica che l'iscrizione non è approvazione, conformità attestata o autorizzazione ([Ministero della Salute: Registro degli integratori](https://www.salute.gov.it/new/it/tema/alimenti-fini-medici-speciali-ed-integratori/registro-degli-integratori-alimentari/)). Usare anche una pagina corrente del titolare/produttore per documentare la presenza del prodotto sul mercato. Per dispositivi e altri articoli usare fonti del produttore o fonti regolatorie pertinenti alla classe del dispositivo.

Quando una fonte manca, è datata o confligge con un'altra, mantenere il dato `NULL` o lo stato `non_verificato` e registrare la discrepanza nella ricerca delle fonti. La presenza di un AIC storico non rende verificati l'AIC corrente, l'autorizzazione o il regime di fornitura: lo stato regolatorio rimane `non_verificato` finché una fonte AIFA individuale e corrente non supporta esplicitamente la claim. Non trasformare autorizzazione in disponibilità; non dedurre prezzo o stock dal sito di un produttore o di un rivenditore. Il gestionale della farmacia non è collegato.

## Migrazione e seed ripetibile

Fare una copia del database prima di applicare una migrazione. Eseguire prima migrazione e seed sulla copia; controllare integrità, chiavi esterne, retrieval e idempotenza. Lo script accetta il passaggio v4→v5 e lascia invariato un catalogo v5.

```powershell
$salesPython = 'C:\Users\bonat\AppData\Local\Python\bin\python.exe'
Copy-Item database\farmacia.sqlite3 database\farmacia-staging.sqlite3
& $salesPython backend\catalog_setup.py migrate-species --catalog database\farmacia-staging.sqlite3
& $salesPython backend\catalog_setup.py seed --catalog database\farmacia-staging.sqlite3 --seed database\catalogo-ampliamento-20261109.json --only-new
& $salesPython backend\catalog_setup.py seed-symptoms --catalog database\farmacia-staging.sqlite3 --symptom-seed database\collegamenti-dolore-pelle-vet.json
& $salesPython backend\catalog_setup.py check --catalog database\farmacia-staging.sqlite3
& $salesPython backend\catalog_wiki.py --seed database\catalogo-ampliamento-20261109.json
& $salesPython backend\catalog_wiki.py --seed database\catalogo-ampliamento-20261109.json --check
```

Il seed di ampliamento si importa con `--only-new`: aggiunge solo codici assenti e preserva i record esistenti, i prezzi, le scorte e i dati demo. L’importazione è ripetibile; un secondo passaggio salta i codici esistenti e riallinea le relazioni candidate senza creare duplicati. Rifiuta prezzi o scorte valorizzati senza fonte della farmacia. I prodotti con presenza corrente italiana non verificata restano nel catalogo e nella wiki come bozze, ma il retrieval live li esclude. I medicinali veterinari hanno specie esplicita; le fonti EMA documentano l’autorizzazione UE, non la disponibilità nella farmacia italiana.

Solo dopo aver verificato la copia si applicano gli stessi comandi al catalogo operativo locale. Conservare un backup datato fino al completamento dei controlli. Lo script non esegue backup automatici e non legge o aggiorna sistemi esterni.

## Relazioni con la wiki

Le schede editoriali restano in `wiki/schede/`. I codici del catalogo sono il riferimento stabile; nomi e alias consentono la ricerca. Aggiornare la wiki solo con fatti e relazioni che abbiano una fonte adeguata e stato di revisione esplicito. Il seed `collegamenti-sintomo.json` contiene collegamenti documentali candidati per raffreddore, congestione nasale e tosse, collegati a fonti ufficiali del prodotto. Il loro stato resta `candidata`: la postazione li distingue chiaramente dalle relazioni revisionate e il farmacista verifica destinatario, avvertenze e indicazione prima di una proposta. Non si derivano associazioni da co-occorrenze o dalle vendite.

Il seed `collegamenti-dolore-pelle-vet.json` aggiunge i collegamenti con fonte per contusioni, ematomi, micosi cutanee, osteoartrosi e parassiti nelle specie esplicitamente distinte. Non crea associazioni per dermatite generica né collegamenti integratore-sintomo o integratore-medicinale. Ogni relazione di indicazione resta `candidata`; una claim `associazione_clinica` verificata registra solo che la fonte dichiara quell’indicazione e non approva la relazione o il consiglio. L’importazione idempotente non cambia stati già approvati o respinti.

```powershell
$salesPython = 'C:\Users\bonat\AppData\Local\Python\bin\python.exe'
& $salesPython backend\catalog_setup.py seed-symptoms --catalog database\farmacia.sqlite3 --symptom-seed database\collegamenti-dolore-pelle-vet.json
& $salesPython backend\catalog_setup.py check --catalog database\farmacia.sqlite3
```

Prima di applicare il seed operativo, fare una copia del file SQLite e verificarla. Il seed modifica solo `fonti`, `concetti`, `relazioni_concetto_prodotto` e `prodotto_fonti`; non cambia prodotti, prezzi, scorte, alias o relazioni di vendita.

## Confezioni documentate

`confezioni.json` è un elenco di gruppi espliciti. Ogni gruppo contiene `source_id` (fonte ufficiale con identità verificata per ogni SKU) e `packages` (oggetto con codice di catalogo → etichetta della confezione). Il banco espone il gruppo soltanto se tutti i codici sono recuperabili e forma, via, concentrazione e ingredienti documentati coincidono. Prezzo e disponibilità vengono letti per codice. Il registro operativo è vuoto perché il seed attuale accorpa le differenze di quantità nello stesso record e non fornisce uno SKU per ciascuna confezione.

`classificazioni.json` è un oggetto indicizzato per codice di catalogo. Ogni record dichiara `classification` (`generico` o `marca`) e `source_id`. Inserire una voce solo se la fonte attesta esplicitamente la classificazione e ha una claim di identità verificata per lo stesso codice. Il registro iniziale è vuoto. Nome e principio attivo da soli non determinano la classificazione.

## Funzioni demo preesistenti

La tabella `offerte` e la coda `reintegro.sqlite3` conservano le funzioni dimostrative. Il calcolo di reintegro considera solo quantità note e i relativi avvisi vengono filtrati sul prodotto visibile. I prodotti reali senza una fonte di scorte rimangono fuori dalla coda di reintegro.

## Listino, scorte e promozioni di prova

`python -m backend.demo_inventory --catalog database/farmacia.sqlite3 --date 2026-11-08 --wiki wiki/LISTINO_DEMO.md` applica lo scenario esplicito di prova. Eseguire con il banco chiuso e dopo il backup. Per ogni SKU idoneo, il modulo inserisce valori sintetici con fonte `SRC-SALES-DEMOBANCO-20261108`. Prezzi e scorte con una fonte diversa restano invariati. Le tre promozioni demo illustrano rispettivamente un’offerta valida, una scaduta e una esaurita. Il listino Markdown deriva dai valori SQLite etichettati dalla stessa fonte.
