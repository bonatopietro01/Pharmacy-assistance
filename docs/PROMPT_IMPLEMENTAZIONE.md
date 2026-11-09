# Prompt per costruire Sales Agents

Realizza ed evolvi Sales Agents, una postazione Windows locale per il farmacista. Parti dall’app esistente e leggi AGENTS.md e docs/TaskState.md. Mantieni frontend/, backend/, database/ e wiki/, l’avvio da AVVIA_BANCO.cmd e il server accessibile dal solo PC.

## Conversazione in diretta

- Inizia soltanto quando il farmacista preme **Inizia ascolto**. Il microfono deve restare attivo durante il dialogo, anche mentre si aggiorna lo schermo. Con Vosk leggi sia le ipotesi parziali sia i segmenti finali. Mostra il testo parziale mentre arriva, sostituiscilo quando cambia e fissa il segmento quando si stabilizza. Il flusso di assistenza deve poter partire anche con parlato continuo, senza aspettare la fine della frase o imporre una pausa.
- A sinistra mostra la trascrizione in diretta. Evidenzia nell’originale i termini e le locuzioni che hanno contribuito alla scheda mostrata e permetti di vedere quale regola e quale fonte li collegano al risultato. Gestisci revisioni delle ipotesi, sovrapposizioni, negazioni, riferimenti al passato e correzioni. Un indizio parziale può apparire come provvisorio. Se viene ritirato, ritira anche la scheda che ne dipende.
- Dopo l’avvio mostra prima «Sto raccogliendo il contesto». Usa una finestra mobile di pochi secondi e attendi sia un intervallo breve configurabile (partenza a circa 3 secondi, da misurare) sia un indizio sufficientemente stabile. Se il contesto manca, mostra una domanda utile da chiarire. Aggiorna progressivamente senza far lampeggiare le schede. Mantieni una sola richiesta in volo e scarta risposte superate.
- Audio, testo, ipotesi di contesto e traccia della sessione restano in memoria. Nessuna copia in file, database, cache, log o servizi remoti. A fine sessione, su reset o disconnessione, rilascia il microfono e svuota lo stato sul server e nella pagina.

## Fasi e comandi

Mostra sempre la fase, il motivo e il dato mancante. Fasi proposte: **Raccolta**, **Domande**, **Verifica prodotto**, **Consiglio confermato**, **Servizio**. Durante le domande mostra al massimo ciò che serve chiarire. Quando compare un prodotto candidato, mostra scheda e scorte. Mostra collegamenti complementari approvati dopo la conferma del prodotto da parte del farmacista. Una citazione o un «non lo voglio» non confermano una vendita. Una correzione rimuove la conferma precedente. Il farmacista può correggere fase e destinatario, bloccare o rilasciare una scheda, confermare il prodotto e azzerare la sessione.

Distingui chi parla da chi userà il prodotto. Usa solo informazioni dichiarate o confermate dal farmacista, per esempio «per mio figlio di 14 anni», «per mio padre di 78 anni», «sono in menopausa» o «cerco un mascara». Lascia sconosciuto ciò che manca. Non dedurre età, sesso, gravidanza, patologie o terapia dalla voce, dal nome o dall’aspetto. Usa questi dati temporanei per chiedere le verifiche pertinenti e filtrare materiale approvato per l’effettivo destinatario. Età e condizioni particolari richiedono verifica delle fonti, non un elenco automatico di farmaci.

## Schermo

- Sinistra: trascrizione con evidenziazione, fase e comandi.
- Destra in alto: foto autorizzata o illustrazione, nome, principio attivo, forma e dosaggio della confezione. Accanto mostra scorte, esaurimento e richiesta interna di reintegro. Se esaurito, mostra le disponibilità degli equivalenti solo quando esiste un collegamento documentato per quella confezione. Stesso principio attivo da solo non basta. Mostra fonte e verifica del farmacista.
- Destra al centro: pochi suggerimenti, cautele e cose da controllare dalle schede pubblicate. Non proporre un secondo medicinale o integratore per compensare un possibile effetto indesiderato. Un complemento terapeutico richiede fonte, condizioni, esclusioni e revisione per quella combinazione. Se mancano questi dati, mostra il controllo da fare. Puoi mostrare complementi cosmetici pertinenti alla richiesta, separati dalle indicazioni cliniche.
- Destra in basso: risposte rapide su servizi, orari, offerte e farmacie di turno. Per il sito della farmacia usa un URL configurato dal gestore. Per i turni usa una fonte territoriale autorevole e chiedi comune e momento se mancanti. Mostra link, località e ora di verifica. Se la fonte non è disponibile, apri il collegamento di consultazione senza inventare una risposta. Per ricerche esterne usa solo campi pubblici selezionati dall’operatore, come comune e data, mai brani di trascrizione o informazioni sanitarie.

## Catalogo, glossario e offerte

Usa SQLite e wiki Markdown esistenti. Estendi catalogo e schede con immagini, composizione, confezione, fonte, stato di revisione e scorte. Il glossario distingue alias del prodotto, segnali di fase, destinatario dichiarato, negazioni, correzioni e richieste di servizio. Usa le liste di equivalenza applicabili e le schede ufficiali AIFA o EMA per i medicinali. Mantieni i casi combinati demo separati dai collegamenti clinici validati.

Crea un pannello offerte compilabile con prodotto, prezzo o beneficio, inizio, fine, disponibilità e criteri commerciali espliciti, come richiesta di un cosmetico o budget dichiarato. Mostra solo offerte attive e disponibili. Non usare salute, età o genere inferiti per decidere prezzo o offerta. Selezione clinica e promozione restano separate. Le scorte basse aprono una sola richiesta interna di reintegro per prodotto, chiusa quando torna sopra soglia.

## Diagnostica

Crea una pagina locale con stato di microfono, modello, ricerca, backend, frontend e fonti esterne. Mostra codici evento, ora, livello, durata e istruzione per verificare l’errore. Consenti di copiare o esportare solo gli eventi tecnici filtrati. Non includere audio, trascrizione, testo di ricerca, profilo del cliente, token, stack trace con input o URL con parametri privati. Mantieni visibile la differenza tra diagnostica tecnica e spiegazione temporanea di una scheda.

## Verifica

Usa gli [scenari combinati della wiki](../wiki/SCENARI_E_FONTI.md) e i dati di `database/002_assistenza.sql` come base per le prove.

Prova parlato continuo, aggiornamenti parziali, ritardo iniziale, negazione e cambio di fase. Prova richieste per sé e per un’altra persona, età non dichiarata, prodotto esaurito con e senza equivalente documentato, offerta scaduta, turni senza comune, perdita del microfono e reset. Verifica ricerca manuale e mancata persistenza di audio, testo e contesto anche nella diagnostica. Misura il tempo prima della prima scheda e dopo una correzione. Distingui prova con voce reale, test sintetici e funzioni che richiedono un sito o un catalogo reale.
