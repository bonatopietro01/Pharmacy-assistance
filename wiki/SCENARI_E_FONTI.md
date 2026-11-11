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
| Contusione | «Ho preso una botta» | Consulta solo eventuali fonti collegate al concetto contusione; non sostituisce il consiglio del farmacista. |
| Ematoma | «Ho un livido» / «ho un ematoma» | Consulta le formulazioni Hirudoid con indicazione esplicita sugli ematomi; non le mostra per eczema o dolore non specifico. |
| Micosi cutanea | «Cerco qualcosa per il piede d’atleta» | Mostra solo le forme cutanee Canesten/Pevaryl con fonte e stato candidato. Non include ovuli o formulazioni genitali. |
| Dermatite | «Ho una dermatite» / «è eczema» | Nessun prodotto viene associato automaticamente: il seed non collega una diagnosi generica a un farmaco. |
| Osteoartrosi animale | «Il mio cane ha artrosi» / «il gatto ha artrosi» | Mostra soltanto il riferimento veterinario EMA della specie detta, etichettato come uso veterinario; non espone dosi, sostituzioni, prezzo o disponibilità locale. |
| Prodotto veterinario senza specie | «Mi serve Solensia» oppure «avete Librela?» senza menzione di cane/gatto | Non seleziona il prodotto veterinario; la specie deve comparire vicino alla menzione o al bisogno. |
| Parassiti animale | «Il cane ha pulci» / «il gatto ha le pulci» | Consulta solo fonti veterinarie per la specie dichiarata. Non trasferisce un prodotto da cane a gatto o a persona. |
| Fase extra | «Le farebbe comodo altro?» / «Vuole aggiungere qualcos’altro?» | Segnale di extra; una frase negata («sono a posto così») ritira le proposte senza selezionare un prodotto. |
| Cassa | «Procediamo con il pagamento» / «andiamo in cassa» | Cambia la fase; le offerte restano filtrate per criterio commerciale e validità. |
| Termine sconosciuto | Trascrizione sintetica con nome inventato o distorto | Nessun alias viene salvato. Il processo di revisione è documentato; il prototipo corrente non ha una coda di proposte runtime. |
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

### Ricerca catalogo, dolore, pelle e veterinaria (consultata 9 novembre 2026)

- La linea ufficiale [Hirudoid](https://hirudoid.it/linea-hirudoid/) documenta le forme 25.000/40.000 UI gel e crema e include gli ematomi nell’indicazione riportata.
- Le pagine ufficiali di [Lasonil Antidolore](https://www.lasonil.it/prodotti/lasonil-antidolore-2/) sono usate solo per la formulazione e l’indicazione esplicita della pagina. Il prodotto non porta un prezzo o una scorta di farmacia.
- [Canesten](https://www.canesten.it/prodotti) e [Pevaryl](https://pevaryl.com/it/prodotti/) documentano formulazioni cutanee per micosi. Le formulazioni vaginali o genitali non sono collegate al concetto «micosi cutanee».
- L’EMA documenta i prodotti veterinari [Librela](https://www.ema.europa.eu/en/medicines/veterinary/EPAR/librela), [Solensia](https://www.ema.europa.eu/en/medicines/veterinary/EPAR/solensia), [NexGard](https://www.ema.europa.eu/en/medicines/veterinary/EPAR/nexgard), [NexGard Combo](https://www.ema.europa.eu/en/medicines/veterinary/EPAR/nexgard-combo) e [Bravecto](https://www.ema.europa.eu/en/medicines/veterinary/EPAR/bravecto). L’autorizzazione UE e la specie target non attestano la disponibilità in una farmacia italiana; la singola giacenza resta `NULL`.
- La documentazione italiana di [Voltaren Emulgel 2%](https://www.haleonhealthpartner.com/content/dam/cf-consumer-healthcare/health-professionals/it_IT/pain/pdf/it-spc-Voltaren-2-Sett24_V9_clean.pdf) supporta forma e composizione. Il materiale ufficiale di [informazioni sul prodotto](https://www.haleonhealthpartner.com/content/dam/cf-consumer-healthcare/health-professionals/it_IT/pdf/Otc_decision_tree_2023.pdf) documenta l’identità della confezione; i prezzi indicativi del documento non sono importati.
- Per gli integratori, la claim autorizzata sul [magnesio](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32012R0432) riguarda la normale funzione muscolare e non afferma trattamento del dolore né compatibilità con uno specifico farmaco. Il [Registro del Ministero della Salute](https://www.salute.gov.it/new/it/tema/alimenti-fini-medici-speciali-ed-integratori/registro-degli-integratori-alimentari/) chiarisce che la notifica non è approvazione né attestazione di conformità del singolo prodotto. Perciò nessun nuovo collegamento integratore-dolore è stato importato.

## Associazioni cliniche e profili

Non è stato nominato un farmacista revisore. Per decisione dell’utente del 7 novembre 2026, le relazioni prodotto-sintomo `indicazione_etichetta` possono restare `candidata` ed essere mostrate solo come riferimenti non revisionati, con una fonte ufficiale per l’affermazione esatta. Non sono suggerimenti né schede di consiglio. Le altre relazioni cliniche e gli abbinamenti integratore–medicinale restano esclusi dal retrieval live finché non sono approvati e non partecipano al retrieval dei complementi. Lo stato `approvata` non si deduce dalla vendita, dalla co-occorrenza o da una somiglianza di ingredienti: richiede i campi di fonte/versione e revisione previsti dal catalogo. Le relazioni demo restano marcate come tali e circoscritte agli scenari di prova.

Età, genere dichiarato e tema di salute possono essere conservati solo come contesto dichiarato della sessione per la richiesta in corso. Non sono criteri per scegliere, ordinare o promuovere prodotti/offerte. Un argomento come menopausa, raffreddore o farmaco in uso apre una scheda di consultazione e una domanda di chiarimento, non una diagnosi o una terapia suggerita.
