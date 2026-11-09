# Scenari combinati e fonti

Stock, prezzi, offerte e relazioni nel catalogo locale sono dimostrativi.

| Caso | Segnale dichiarato | Esito atteso |
|---|---|---|
| Cosmetico | «Cerco un mascara waterproof», poi «Come lo rimuovo?» | Mascara Demo e offerta demo pertinente. Mostra Struccante Demo dopo la seconda richiesta. L’offerta scaduta resta fuori. |
| Confezione esaurita | Il farmacista conferma DEMO-EQV-01 | Scorta zero e reintegro. DEMO-EQV-02 compare con sette unità come equivalente di prova. Escludi prodotti privi di collegamento documentato. |
| Menopausa o pillola | «Sono in menopausa» oppure «Ho una domanda sulla pillola» | Apri il tema in fase domande e chiarisci la richiesta; non selezionare un prodotto dalla sola condizione dichiarata. |
| Ragazzo | «È per mio figlio di 14 anni» | Distingui chi parla dal destinatario. L’età da sola non seleziona un medicinale o un’offerta; verifica i limiti di età solo per un prodotto richiesto e con una fonte pertinente. |
| Persona anziana | «È per mio padre di 78 anni, prende già delle medicine» | Resta in verifica finché si chiariscono prodotti e richiesta. L’età o una terapia dichiarata non attivano un cross-sell. |
| Farmaco e integratore | «Prendo già un medicinale. Posso abbinarci un integratore?» | Chiarisci i prodotti esatti e consulta fonti autorizzate. Senza una relazione approvata e verificata non mostrare un abbinamento o una compatibilità automatica. |
| Sintomo con fonte | «Ho il raffreddore», «ho il naso chiuso», «ho tosse secca» | Dopo la stabilizzazione, mostra solo le relazioni candidate `indicazione_etichetta` del concetto esatto, con nome prodotto, claim della fonte e stato non revisionato. Non ordina i prodotti e non produce un consiglio. Negazione, uso passato o correzione ritirano i match. |
| Servizio | «C’è una farmacia di turno stasera?» | Chiedi comune e momento, poi consulta la fonte territoriale. |

## Casi per trascrizione e flusso di vendita

Questi casi sono fixture sintetiche per verificare la schermata e il trattamento del testo. Non sono associazioni terapeutiche.

| Dialogo/evento | Comportamento verificabile |
|---|---|
| Partial «cerco un masca…» poi «cerco un mascara waterproof» | La partial sostituisce la precedente; dopo il ritardo configurato e un segnale stabile compare una scheda provvisoria con la frase evidenziata. |
| La partial passa da «cerco mascara» a «non cerco mascara» | Rimuove il relativo interesse e l’offerta; non conserva la scheda ritirata come suggerimento attivo. |
| «L’ho usato il mese scorso» | Marca il riferimento come passato; non conferma né propone la vendita corrente. |
| «Cerco un mascara», poi il farmacista conferma Mascara Demo | Mostra l’offerta attiva solo se date, disponibilità e criterio esplicito coincidono. Il collegamento cosmetico al detergente resta distinto dai suggerimenti clinici. |
| «Per mio figlio di 14 anni» | Mostra destinatario e dato dichiarato temporanei. Non deduce altri attributi e non seleziona automaticamente un medicinale. |
| «C’è una farmacia di turno?» senza comune/data | Chiede il campo mancante. Senza fonte configurata non mostra una risposta né apre una ricerca con testo della conversazione. |
| Comune e data inseriti dal farmacista con fonte turni configurata | Un click apre il collegamento pubblico usando soltanto quei campi; la schermata dichiara che non ha letto né verificato la pagina esterna. |
| Fine, reset o lease scaduta | Svuota trascrizione, destinatario, evidenze, schede e conferme; la diagnostica conserva soltanto codici tecnici. |

Le misure di ritardo vanno riportate separando eventi sintetici, prova al microfono e consultazione effettiva di una fonte esterna. I link esterni non sono fonti verificate dall’app finché il farmacista non consulta la pagina.

## Riferimenti verificati

- AIFA documenta i criteri di equivalenza per confezione e pubblica le liste applicabili. [FAQ AIFA](https://www.aifa.gov.it/it/domande-e-risposte-su-farmaci-equivalenti) · [Liste di trasparenza](https://www.aifa.gov.it/it/liste-di-trasparenza)
- Per un esempio di scheda cosmetica con ingredienti e foto del produttore. [Toleriane Mascara Waterproof](https://www.larocheposay.it/make-up-toleriane-il-trucco-con-tollerabilita-ottimale/toleriane-mascara-waterproof-la-roche-posay)
- Esempio di dispositivo medico con istruzioni specifiche. [Melilax, Aboca](https://www.aboca.com/it/prodotto/melilax-adulti-ns-6-microc10g/)
- Intrarosa contiene prasterone e richiede prescrizione. La fonte serve alla cura della scheda professionale. [EMA](https://www.ema.europa.eu/it/medicines/human/EPAR/intrarosa)
- Per l’abbinamento farmaco–integratore verificare ingredienti, etichetta e compatibilità dei prodotti effettivi. [Ministero della Salute](https://www.salute.gov.it/new/it/prodotti-editoriali/decalogo-un-uso-corretto-degli-integratori-alimentari-2019/)
- **Probiotici e antibiotici.** Le indicazioni consultate non supportano un’associazione generica tra un antibiotico e un integratore probiotico: la linea guida AGA descrive ceppi/formulazioni specifici in contesti specifici; la linea guida ACG raccomanda contro i probiotici per la prevenzione primaria di *C. difficile*. Il Ministero descrive i probiotici come ingredienti di alimenti/integratori, senza stabilire la compatibilità con uno specifico medicinale. Poiché le raccomandazioni differiscono e non è stato identificato un farmacista revisore né mappato uno specifico prodotto, il database non crea e la postazione non mostra un abbinamento. Vedi il [registro della revisione](REVISIONE_ASSOCIAZIONI.md).
- ATS Milano è un esempio di fonte territoriale. Il comune e il sito della farmacia effettiva sono da configurare. [ATS Milano](https://www.ats-milano.it/ats/carta-servizi/guida-servizi/farmaci-farmacie/farmacie)

## Associazioni cliniche e profili

Non è stato nominato un farmacista revisore. Per decisione dell’utente del 7 novembre 2026, le relazioni prodotto-sintomo `indicazione_etichetta` possono restare `candidata` ed essere mostrate solo come riferimenti non revisionati, con una fonte ufficiale per l’affermazione esatta. Non sono suggerimenti né schede di consiglio. Le altre relazioni cliniche e gli abbinamenti integratore–medicinale restano esclusi dal retrieval live finché non sono approvati e non partecipano al retrieval dei complementi. Lo stato `approvata` non si deduce dalla vendita, dalla co-occorrenza o da una somiglianza di ingredienti: richiede i campi di fonte/versione e revisione previsti dal catalogo. Le relazioni demo restano marcate come tali e circoscritte agli scenari di prova.

Età, genere dichiarato e tema di salute possono essere conservati solo come contesto dichiarato della sessione per la richiesta in corso. Non sono criteri per scegliere, ordinare o promuovere prodotti/offerte. Un argomento come menopausa, raffreddore o farmaco in uso apre una scheda di consultazione e una domanda di chiarimento, non una diagnosi o una terapia suggerita.
