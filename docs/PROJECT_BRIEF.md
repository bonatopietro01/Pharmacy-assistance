# Brief del progetto — 7 novembre 2026

Il brief distingue le esigenze confermate dalle proposte. La specifica della prima prova è collegata in fondo.

## Cosa ha chiesto l'utente

Affiancare il padre, farmacista al banco, con uno schermo riservato a lui. Lo schermo combina immagini, informazioni scritte sul prodotto, dati di vendita e contenuti utili a formulare un consiglio al cliente. Il farmacista può consultare quello che gli serve mentre il contenuto si aggiorna in base alla conversazione.

Il sistema dovrebbe capire quando un prodotto è stato consigliato e passare ad altre informazioni utili. L'esempio del raffreddore illustra questo passaggio, senza definire quali medicinali o associazioni siano appropriati.

Decisione dell'utente del 7 novembre 2026: la postazione riservata al farmacista può mostrare collegamenti candidati tra un sintomo riconosciuto e prodotti del catalogo prima della revisione del farmacista. Ogni collegamento deve avere una fonte ufficiale esplicita e restare chiaramente etichettato come non revisionato; non è un consiglio automatico né una scelta del prodotto ideale. L'esempio del raffreddore continua a non autorizzare collegamenti ricavati da co-occorrenza, né dosaggi, diagnosi o personalizzazioni non dichiarate.

L'utente vuole definire regole, raccogliere casi e migliorare nel tempo la pertinenza dei suggerimenti rispetto alla persona, al problema e ai dati disponibili. Ha chiesto di leggere App_starter_pack e PROMPTME, adattare gli agenti e fare domande per migliorare il progetto.

## Prima prova implementata

- Il catalogo SQLite di prova contiene 12 prodotti sintetici (farmaci, cosmetici e articoli dimostrativi); il gestionale della farmacia resta da identificare.
- Una wiki Markdown collega schede, termini di ricerca e relazioni al catalogo.
- La modalità operativa usa Vosk locale e parte solo quando il farmacista preme **Inizia ascolto**. I dialoghi sintetici restano disponibili per ripetere casi e controllare negazioni, correzioni, fasi e reset.
- La conferma del prodotto è manuale. Audio e contesto di sessione non vengono persistiti. Consultazioni esterne richiedono link pubblici configurati e un click dell’operatore.

## Proposte da discutere

1. **Informazioni verificabili.** Ogni scheda dovrebbe collegarsi a un record del catalogo e alla fonte che giustifica il contenuto. Il catalogo commerciale, da solo, non dimostra appropriatezza clinica.
2. **Comprensione della conversazione.** Distinguere prodotto menzionato, escluso, già usato, proposto dall'operatore o accettato dal cliente. Una menzione non è una vendita e una trascrizione parziale può cambiare significato.
3. **Aggiornamento leggibile.** Cambiare scheda quando il contesto cambia in modo attendibile, evitando rotazioni continue. Prevedere pausa, correzione e nuova sessione. Durata minima, soglie e latenza vanno concordate.
4. **Regole prima dell'apprendimento.** Separare condizioni di ammissibilità, selezione e ordinamento. Disponibilità e preferenze commerciali possono agire soltanto fra opzioni ammissibili.
5. **Apprendimento revisionato.** Raccogliere feedback espliciti; proporre modifiche alle regole con motivazione, casi e versione; far approvare quelle modifiche dal responsabile del dominio prima della promozione. Una vendita o un clic non attestano sicurezza o beneficio clinico.
6. **Personalizzazione circoscritta.** Iniziare dal contesto della singola sessione, senza presumere che serva riconoscere o conservare un profilo del cliente. L'eventuale memoria fra visite è una decisione separata.
7. **Dati minimizzati.** Valutare un'elaborazione con audio temporaneo e casi anonimizzati. Ascolto reale, conservazione e uso di servizi remoti richiedono prima una scelta esplicita sul flusso dei dati e sui requisiti applicabili.

Le prime tre proposte sono state specificate nel prompt allegato e implementate in forma deterministica per il prototipo. L'apprendimento revisionato e le regole cliniche reali restano futuri; gli agenti di sviluppo non hanno autorità clinica.

## Tracce illustrative, solo sintetiche

| Conversazione | Distinzione richiesta | Comportamento da discutere |
|---|---|---|
| «Non voglio il prodotto X» | Negazione | Non segnare X come consigliato o accettato. |
| «Il prodotto X l'ho usato il mese scorso» | Uso passato | Non dedurre una raccomandazione attuale. |
| L'operatore propone X, poi si corregge su Y | Revisione dell'intenzione | Rivalutare lo stato; non conservare X come decisione finale. |
| Arriva un'altra persona al banco | Nuova sessione | Ripulire il contesto prima di riutilizzarlo. |
| Il database non supporta un contenuto | Evidenza mancante | Attendere una verifica o mostrare un'informazione neutra concordata. |

X e Y sono segnaposto. Queste tracce non sono consigli medici, regole di associazione o prove eseguite.

## Materiali della prova

Il catalogo operativo e la guida sono in [database](../database/README.md) e [frontend](../frontend/README.md). La specifica iniziale documenta il dialogo sintetico; il [contratto runtime](CONTRATTO_SESSIONE.md) e il [TaskState](TaskState.md) descrivono la versione attuale.
