# Prima prova al banco

Proposta di specifica del 7 novembre 2026 per una schermata, un dialogo ripetibile e la consultazione manuale di un catalogo con wiki.

## Approcci discussi

| Modalità | Cosa permette di verificare per prima | Dipendenza principale |
|---|---|---|
| Dialogo simulato a turni | La stessa frase produce lo stesso stato e si vede quale passaggio fa cambiare la scheda | Sequenza di prova con eventi già assegnati |
| Microfono con dialogo di prova | Si osserva anche la trascrizione e l'effetto degli errori di ascolto | Acquisizione audio e riconoscimento della voce |

L'utente ha scelto il dialogo simulato a turni. La schermata riceve eventi espliciti del caso di prova. La classificazione automatica di una conversazione e l'audio rientrano nella fase successiva.

## Schermata proposta

Una pagina locale riservata al farmacista. Il dialogo occupa una zona con il parlante e l'ultimo turno. La scheda del prodotto mostra una rappresentazione grafica del formato, il nome, la categoria, il prezzo e la disponibilità simulati. La zona di consultazione mostra la scheda wiki o il promemoria collegato alla fase del dialogo.

Il farmacista può avanzare di un turno, ricominciare o cercare un prodotto e una voce wiki. Il catalogo e la wiki usano il database SQLite di prova. Il codice prodotto collega la scheda anagrafica alla voce wiki. [Materiali demo](../../../demo/README.md)

Le schede dimostrative usano i prezzi, le scorte e le descrizioni fittizi del catalogo. Una futura scheda per un medicinale reale deve collegare i contenuti clinici alla fonte aggiornata del prodotto. Per i medicinali autorizzati in Italia, l'AIFA rende consultabili il riassunto delle caratteristiche del prodotto e il foglio illustrativo. [AIFA](https://www.aifa.gov.it/riassunto-caratteristiche-e-foglio-illustrativo)

## Sequenza proposta

Il replay aggiunge una conferma esplicita alla traccia della wiki, così il farmacista può vedere la differenza fra aprire una scheda e confermare la scelta.

| Turno | Evento | Risultato visibile |
|---|---|---|
| 1 | Il cliente cita Banco Demo A come già usato per un caso di raffreddore | Si vede il contesto della conversazione. Il prodotto citato risulta già usato e la selezione rimane vuota. |
| 2 | Il farmacista apre Banco Demo B | Appaiono il prodotto B, la scheda corrispondente, il prezzo e le scorte simulate. |
| 3 | Il farmacista conferma la scelta di Banco Demo B | Il prodotto rimane visibile e la zona di consultazione passa al promemoria sulla disponibilità. |
| 4 | Il farmacista si corregge e apre Banco Demo C | La selezione passa a C e il suo stato è «Non disponibile». La conferma precedente viene rimossa. |

## Verifica della prova

- Il comando per avanzare aggiorna tutte le zone con i dati del turno corrente. Il reset riporta il dialogo e la selezione all'inizio.
- Cercando «raffreddore» si ritrova la pagina del caso. Cercando il codice `DEMO-OTC-02` si apre la scheda esatta del prodotto B.
- Una ricerca senza corrispondenze mostra uno stato vuoto. I nomi, prezzi e scorte visualizzati corrispondono alle righe del database.
- Le associazioni fra eventi e contenuti sono leggibili in un caso ripetibile. I futuri feedback del farmacista possono diventare casi separati per valutare le modifiche alle regole.

La demo consente di valutare utilità e chiarezza della schermata. La valutazione dell'ascolto, la revisione dei consigli e l'apprendimento dai casi richiedono prove successive.
