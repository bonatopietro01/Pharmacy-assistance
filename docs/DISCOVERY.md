# Decisioni aperte

Questo elenco guida la conversazione. Non è un questionario da somministrare tutto insieme: usare le risposte già ricevute e approfondire soltanto ciò che cambia il progetto.

## Scelte confermate il 7 novembre 2026

- Il padre è farmacista e lavora in farmacia. Solo lui vede lo schermo.
- La prova usa farmaci da banco e integratori simulati con una wiki consultabile. Il gestionale in uso resta un dato da acquisire quando servirà integrare la farmacia reale.
- Il dialogo simulato a turni serve per le prove ripetibili; il prompt successivo autorizza anche l’ascolto locale in tempo reale, avviato manualmente dal farmacista.
- Le schede della wiki si curano in Markdown. I contenuti clinici reali passano dalla verifica di un farmacista prima di essere pubblicati al banco.
- La trascrizione è temporanea. Le ipotesi partial possono cambiare; la prima scheda automatica attende un segnale stabile e un ritardo configurabile inizialmente pari a 3 secondi.
- La fase e il destinatario sono correggibili dal farmacista; il prodotto resta non confermato finché il farmacista non lo conferma.
- Il programma mostra offerte solo con criteri commerciali espliciti. Età, genere e salute non decidono promozioni.
- Le fonti pubbliche per farmacia, orari e turni sono link HTTPS configurabili. L’app non legge automaticamente il sito; località e data devono essere compilate dall’operatore.

## Round di progettazione dell’app

Il piano iniziale e il [prompt](PROMPT_IMPLEMENTAZIONE.md) hanno guidato l’implementazione descritta in [TaskState](TaskState.md) e [contratto sessione](CONTRATTO_SESSIONE.md).

| Domanda | Proposta | Stato |
|---|---|---|
| Q1. Come si aggiorna la wiki? | Schede Markdown curate dal progetto, con verifica dei contenuti clinici | Confermata |
| Q2. Cosa fa scattare il passo successivo? | Contesto stabile e ritardo breve; la scheda è provvisoria e la conferma è un’azione del farmacista | Definita nel prompt ed implementata |
| Q3. Come si apre l’ascolto? | Una sessione avviata e chiusa esplicitamente dal farmacista | Definita nel prompt ed implementata |

## Decisioni ancora aperte per il pilot reale

- **Casi reali da modellare:** la qualità del riconoscimento deve essere provata con dialoghi consentiti e controllati; i test automatici attuali usano eventi sintetici.
- **Responsabile delle regole:** chi sarà il farmacista che revisiona schede e regole reali? Quali fonti e date devono accompagnare i contenuti clinici?
- **Personalizzazione:** servono solo informazioni dichiarate durante la conversazione o una memoria fra visite? Non proporre profili persistenti prima di averne chiarito lo scopo.
- **Ascolto e dati:** la prova locale non salva audio o trascrizioni. Il pilot deve verificare l’hardware e i requisiti applicabili prima di ascoltare clienti reali.
- **Fonti e servizi:** quali URL pubblici ufficiali usare per la farmacia effettiva e per i turni, e a quale comune/data si riferiscono?
- **Dispositivi e condizioni:** quali computer, schermo e microfono sono disponibili; che rumore e connettività ci sono; il ritardo iniziale va misurato sul dialogo reale?
- **Successo e apprendimento:** quali errori sono più gravi; quali feedback può dare l'operatore; come misurare utilità senza confondere vendita e appropriatezza?

Le proposte iniziali sono nel brief; nessuna risposta viene assunta dal silenzio dell'utente.
