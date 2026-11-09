# Sales Agents · pack Codex

Questo derivato locale mantiene le configurazioni di sviluppo per Codex. Il pack Full_stack esterno è stato letto come riferimento e resta intatto; la fonte canonica adattata al progetto è `agent-kit/source/`.

## Agenti

I TOML di progetto sono in `.codex/agents/`; le specifiche adattate sono in `Agents/`.

| ID | Ruolo |
|---|---|
| `prompt-agent` | Prepara o migliora prompt su richiesta; sola lettura. |
| `app-starter` | Distingue app nuova, esistente e in esecuzione; conserva la specializzazione Sales Agents. |
| `architect` | Definisce contratti e scelte trasversali; sola lettura. |
| `backend` | Dati, sessioni, regole e API. |
| `frontend` | Schermate e flussi operativi. |
| `ai-engineer` | Eventi, retrieval, prompt e feedback revisionato. |
| `reviewer` | Review di correttezza e provenienza; sola lettura. |

AppStarter è una personalizzazione del progetto che si mantiene anche se il README Full_stack elenca sei ruoli.

## Skills

Le dodici cartelle in `Skills/` vengono installate in `.agents/skills/` con `SKILL.md`, metadati e risorse. Il set comprende le undici skill già adattate e `folder-structure` proveniente da `Full_stack_pack`.

Per nomi, trigger e dipendenze leggi [Skills/README.md](Skills/README.md). Per la configurazione e la verifica leggi [agent-configuration](Skills/agent-configuration/SKILL.md) e i riferimenti Codex collegati.

## Installazione locale

Il generatore prepara solo `.codex/agents/`, `.agents/skills/`, `agent-kit/WORKFLOW.md` e il collegamento in `AGENTS.md`. Esegui prima l'anteprima, risolvi i conflitti, poi usa `--apply` e `--check` con il generatore indicato in [PROMPTME.md](PROMPTME.md). I file restano configurazioni dell’assistente di coding e non attivano agenti dentro l’app.
