# Glossario di ricerca

## Segnali della conversazione

| Tipo | Parole e locuzioni | Uso nel prototipo |
|---|---|---|
| Raccolta | Apertura di sessione, contesto incompleto | Fase iniziale. Non suggerisce un prodotto. `sales_stage=collecting` |
| Domande e verifica | «per chi è», «da quanto», «cosa ha già provato», «cerco [prodotto]», «quanto costa?» | Raccoglie la richiesta o una verifica esplicita. La richiesta di un prodotto è fase domande, non cross-selling. `sales_stage=questions` |
| Prodotto da verificare | «mi controlla Banco Demo A», «è disponibile Banco Demo B?» | Consulta l’alias univoco, la scheda e le scorte. `conversation.product_candidate` |
| Proposta | «le propongo Banco Demo A», «le consiglio [prodotto]» | Segnale testuale per fase proposta. Serve un prodotto corrispondente stabile; non dimostra appropriatezza clinica. `conversation.proposal`, `sales_stage=proposal` |
| Accettazione | «va bene», «prendo [prodotto]» | Segnale verbale di accettazione da tenere distinto dalla proposta. «Va bene» da solo non identifica l’oggetto né il parlante. `conversation.acceptance`, `sales_stage=sale` |
| Chiusura | «serve altro?», «le occorre altro?», «desidera altro?», «posso aiutarla con altro?» | Segnala la fase di chiusura e l’invito a proseguire. Non dimostra che sia avvenuta una vendita. `conversation.closing_signal`, `sales_stage=closing` |
| Negazione e rifiuto | «non cerco il mascara», «non lo voglio» | Ritira il candidato e l’interesse commerciale associati. `conversation.negation`, `conversation.refusal` |
| Uso passato | «lo prendevo», «l’ho usato il mese scorso» | Tratta il prodotto come una citazione. `conversation.past`, `conversation.product_mention` |
| Correzione | «anzi, cerco uno struccante», «intendevo Banco Demo B» | Rivaluta la scelta precedente. `conversation.correction` |
| Destinatario dichiarato | «è per me», «è per mio figlio di quattordici anni», «è per una donna» | Mostra relazione, età o genere quando dichiarati per il destinatario. `conversation.recipient` |
| Interesse commerciale | «cerco un mascara waterproof», «quanto costa il mascara?», «con budget di 15 euro» | Associa la richiesta esplicita e l’eventuale budget al prodotto identificato. `conversation.commercial_intent` |
| Rimozione del trucco | «come lo rimuovo?», «come rimuovere il mascara?» | Segnala la richiesta per consultare un eventuale collegamento cosmetico autorizzato nel catalogo. `conversation.cosmetic_removal` |
| Argomenti da chiarire | «sono in menopausa», «pillola contraccettiva», «prendo già un medicinale», «effetto indesiderato» | Apri una scheda di consultazione pertinente e chiedi quale informazione serve. `conversation.topic` |
| Sintomi ricercabili | «raffreddore», «naso chiuso», «congestione nasale», «tosse secca», «tosse grassa» | Mantiene distinto il concetto espresso e cerca soltanto relazioni sintomo-prodotto candidate con una fonte esplicita. `conversation.topic` → `symptom_matches` |
| Servizi | «farmacia di turno», «aperta stasera», «orari», «sito web» | Apri la consultazione. Per i turni chiedi al farmacista comune e data. `conversation.service_turni`, `conversation.service_orari`, `conversation.service_sito` |

I segnali della fase sono `collecting`, `questions`, `proposal`, `sale` e `closing`. Ogni cambio deriva da una locuzione testuale riconosciuta e deve diventare stabile nella trascrizione prima che il backend lo applichi. Una frase isolata non identifica chi l’ha pronunciata, a chi si riferisce o se la proposta sia stata accettata. Un segnale di chiusura può rendere valutabile una relazione approvata già presente nel catalogo; non trasforma una relazione candidata in un consiglio.

I nomi, i codici e gli alias esplicitamente registrati arrivano dal catalogo SQLite. Anche i principi attivi medicinali possono trovare i prodotti corrispondenti. Gli ingredienti degli integratori (vitamine, minerali, estratti e probiotici) sono indicizzati separatamente e mostrati come «ingredienti», mai come «principi attivi» medicinali. Il campo `termini`, il titolo e il testo indicizzano la scheda wiki per argomento; non diventano alias di un prodotto. Per riconoscere un prodotto si usano solo nome, codice, alias registrati e ingredienti presenti con provenienza. La ricerca non crea relazioni cliniche dalla co-occorrenza di termini.

| Frammento di esempio | Scheda consultabile |
|---|---|
| raffreddore, comune raffreddore | [Raffreddore](schede/raffreddore.md) |
| naso chiuso, naso tappato, congestione/ostruzione nasale | [Congestione nasale](schede/congestione-nasale.md) |
| tosse, tosse secca, tosse grassa o produttiva | [Tosse](schede/tosse.md) |
| Banco Demo B, DEMO-OTC-02 | [Banco Demo B](schede/banco-demo-b.md) |
| magazzino, scorte, disponibilità | [Lettura della disponibilità](schede/lettura-disponibilita.md) |

Nella ricerca la frase completa contribuisce all’ordinamento e le locuzioni riconosciute hanno priorità sui singoli termini. Nell’ascolto automatico la richiesta e il nome/alias devono appartenere alla stessa locuzione per aprire una verifica commerciale. Le ipotesi parziali producono indizi provvisori aggiornati sulla revisione corrente e non bastano da sole a mostrare una scheda.

Negazioni, rifiuti, correzioni e riferimenti a uso passato ritirano o limitano l’evidenza cui si riferiscono. I collegamenti sintomo-prodotto della prova possono essere mostrati prima della revisione del farmacista solo con etichetta «indicazione riportata dalla fonte · associazione non revisionata», fonte consultabile e claim limitata al testo supportato. Non sono un consiglio, una graduatoria o una scelta di prodotto ideale. Se prodotto o riferimento non sono chiari, si mantiene la richiesta in verifica invece di inventare una diagnosi, una dose, una compatibilità o un profilo del cliente. Il destinatario è mostrato solo quando dichiarato nel dialogo corrente.
