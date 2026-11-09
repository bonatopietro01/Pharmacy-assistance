# Verifica nel client Codex

Questa procedura distingue configurazione statica, riconoscimento nel programma e chiamata effettiva. Nel repository si eseguono soltanto i controlli dei file e del generatore; le deleghe runtime richiedono un task pertinente e autorizzato.

1. Registra il client/progetto aperto e il pack indicato dal manifest. Esegui il generatore con `--check`; risolvi eventuali errori prima di chiamare un ruolo.
2. Confronta gli ID in `agent-kit/INSTALLATION.json` con il catalogo dei subagenti esposto dalla sessione. Controlla le skills nel selettore effettivamente disponibile. La presenza su disco è **GENERATO**; `--check` superato è **CONTROLLATO_STATICAMENTE**; la presenza nel catalogo è **RICONOSCIUTO**.
3. Per verificare un ruolo usa un incarico di sola lettura adatto alla sua responsabilità, con obiettivo, requisiti, fonti e output. Registra lo strumento di delega, l’ID selezionato e l’esito; una risposta della chat principale non dimostra che sia stata fatta una delega.
4. Per una skill ordinaria osserva l’invocazione esplicita o il caricamento delle istruzioni supportati dal client. Per `handoff` e `retro` mantieni la policy di invocazione esplicita in `agents/openai.yaml`; non eseguire la procedura leggendo il file se Codex richiede l’invocazione dell’utente.
5. Se una voce manca, diagnostica nome, TOML/frontmatter, percorso, dipendenze, permessi, impostazioni degli agenti, versione del client e necessità di riaprirlo. Correggi soltanto la causa trovata e riprova una volta.

Consegna gli stati `FILE_GENERATI`, `CONTROLLATO_STATICAMENTE`, `RICONOSCIUTO` e `CHIAMATA_VERIFICATA`, con evidenze separate. Un client o una chiamata non verificati restano **NON_VERIFICATI**; non stimare prestazioni dal solo controllo dei file.
