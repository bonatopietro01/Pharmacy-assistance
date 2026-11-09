# Adattamento Codex — 9 novembre 2026

## Risultato

Sales Agents mantiene sette ruoli di sviluppo in formato Codex (`.codex/agents/*.toml`) e dodici skills in `.agents/skills/`. I sei ruoli e le dodici skills descritti nel README di `Full_stack_pack` sono stati adattati alla struttura Codex; è stato conservato anche `app-starter`, personalizzazione già presente nel progetto. La skill `folder-structure`, presente nel Full_stack pack e assente dal set precedente, è stata aggiunta alla raccolta locale.

Le copie generate per Claude Code e Cursor, i relativi riferimenti di configurazione e il blocco gestito in `CLAUDE.md` sono stati rimossi. Il testo manuale residuo di `CLAUDE.md` è stato preservato. Il pack Full_stack esterno e la fonte originale App_starter_pack non sono stati modificati.

## Ruoli conservati

| ID | Responsabilità |
|---|---|
| prompt-agent | Prompt su richiesta, distinzione fra istruzioni, dati e proposte aperte |
| app-starter | Avvio dopo la discovery; configurazione agenti distinta dal prodotto |
| architect | Contratti fra conversazione, catalogo, regole, schermo e feedback |
| backend | Catalogo, sessioni, regole versionate e aggiornamenti attendibili |
| frontend | Schede visive, pubblico dello schermo, pausa, correzione e reset |
| ai-engineer | Eventi conversazionali, retrieval fondato sulle fonti e feedback revisionato |
| reviewer | Provenienza, negazioni, correzioni, isolamento e limiti delle evidenze |

## Fonte e controlli

- Le fonti adattate sono in `agent-kit/source/`; l'installatore locale genera solo i percorsi Codex.
- `INSTALLATION.json` elenca file, hash, sorgenti e responsabilità gestite; `DERIVATION.json` registra la provenienza dei file sorgente.
- Anteprima, applicazione e `--check` verificano struttura, formati, link e hash. Questi controlli non dimostrano il caricamento runtime dei ruoli o l'invocazione delle skills.
- Non sono state eseguite verifiche nell'applicazione Sales Agents né chiamate reali agli agenti.

Per il formato dei subagenti consultare la [documentazione Codex](https://learn.chatgpt.com/docs/agent-configuration/subagents); per le skills consultare [Codex skills](https://developers.openai.com/codex/skills).
