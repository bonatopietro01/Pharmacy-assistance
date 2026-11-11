# Revisione di termini e alias

## Scopo

Un termine non riconosciuto può aiutare a migliorare il glossario o un alias di prodotto, ma non deve modificare in autonomia il catalogo né influenzare le schede delle sessioni successive.

## Flusso editoriale previsto

1. Il rilevatore lavora solo sul testo stabile che è già presente nella sessione volatile. La proposta scompare al reset, alla chiusura o alla scadenza della sessione.
2. Se il termine non corrisponde a un record, lo mostra come **termine da verificare**, senza conservarlo in SQLite, file o log.
3. La proposta indica il tipo (`nome commerciale`, `alias`, `principio attivo`, `sintomo`, `segnale di fase` o `termine non classificato`), il record candidato e la fonte necessaria per la verifica.
4. Per un alias di prodotto, l’operatore apre una fonte primaria corrente che mostri il nome riferito al codice candidato. Per un principio attivo si controlla anche la composizione; per un sintomo o una frase di fase si verifica il significato e il rischio di negazioni o ambiguità.
5. Solo dopo una conferma esplicita si aggiunge l’alias in `alias_prodotto` o il termine curato nel glossario. Si conserva il riferimento alla fonte e la data della verifica. Un termine incerto viene respinto o lasciato fuori.
6. Il termine approvato abilita al massimo la ricerca dello stesso prodotto o concetto verificato. Non crea relazioni cliniche, idoneità, associazioni integratore-farmaco, informazioni commerciali o profili del destinatario.

## Campi minimi di una proposta effimera

- termine esatto osservato;
- tipo di termine suggerito;
- codice del record candidato, se esiste;
- URL e titolo della fonte primaria ancora da controllare;
- stato `da verificare`, `approvata` o `respinta` e autore della revisione.

La proposta in attesa resta solo nella memoria della sessione. Se l’operatore approva, si persiste esclusivamente il termine autorizzato, il record e la provenienza; non si archivia la frase, l’audio o il resto della conversazione.

## Limite dell’implementazione corrente

Il catalogo e il glossario correnti non raccolgono né salvano automaticamente termini sconosciuti. Questa pagina definisce il processo da implementare; finché non esiste un controllo di revisione esplicito, una parola non riconosciuta resta volatile e non cambia il retrieval.
