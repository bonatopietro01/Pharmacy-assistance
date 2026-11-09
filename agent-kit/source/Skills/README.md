# Skills Codex · Sales Agents

Il pack comprende dodici skills in formato `SKILL.md`, installate solo in `.agents/skills/`. La specifica nella cartella è il punto d’ingresso; risorse e script restano nella stessa cartella e vengono coperti dal manifest.

| Skill | Usala quando |
|---|---|
| [agent-configuration](agent-configuration/SKILL.md) | Crei o aggiorni un ruolo o un pack Codex. |
| [requirement-traceability](requirement-traceability/SKILL.md) | Mantieni requisiti, criteri, ownership e prove tra passaggi. |
| [project-graph-context](project-graph-context/SKILL.md) | Le relazioni del progetto aiutano a capire dipendenze e impatto. |
| [pipeline-benchmark](pipeline-benchmark/SKILL.md) | L’utente richiede un confronto ripetibile di pipeline. |
| [folder-structure](folder-structure/SKILL.md) | Serve leggere o confrontare l’albero di cartelle e individuare percorsi. |
| [grilling](grilling/SKILL.md) | Una decisione sostanziale è aperta e cambia il risultato. |
| [handoff](handoff/SKILL.md) | L’utente richiede di preparare una nuova sessione. |
| [writing-for-agents](writing-for-agents/SKILL.md) | Scrivi o revisioni istruzioni destinate ad agenti. |
| [codebase-design](codebase-design/SKILL.md) | Definisci confini di moduli, interfacce o responsabilità. |
| [retro](retro/SKILL.md) | L’utente richiede una retrospettiva della sessione. |
| [investigate-first](investigate-first/SKILL.md) | La causa di un problema non è ancora chiara. |
| [safe-refactor](safe-refactor/SKILL.md) | Riordini codice mantenendo comportamento e compatibilità. |

Le undici skills preesistenti mantengono le loro fonti e personalizzazioni Sales Agents. `folder-structure` è stato importato da `Full_stack_pack/Skills/folder-structure/` indicato dall’utente. I riferimenti per agent-configuration descrivono solo il formato e l’installazione Codex.

## Dipendenze

- `agent-configuration` include il generatore locale, la mappa dei ruoli, i riferimenti Codex e `runtime-check.md`.
- `writing-for-agents` include `SKILL-MECHANICS.md` per creare o cambiare una skill.
- `codebase-design` include `DEEPENING.md` e `DESIGN-IT-TWICE.md` per i casi pertinenti.
- `retro` richiama `writing-for-agents`.
- `requirement-traceability` può richiamare `project-graph-context`, `grilling`, `handoff` e `retro` nei rispettivi casi.
- `pipeline-benchmark` richiama `requirement-traceability` e `project-graph-context`.
- `project-graph-context` include `references/obsidian-workflow.md`.
- `handoff` e `retro` richiedono invocazione esplicita secondo la policy Codex conservata in `agents/openai.yaml`.

Carica solo le skills e le risorse attivate dal task. Il file presente non prova che Codex abbia riconosciuto o invocato la skill. I ruoli in sola lettura e i permessi effettivi restano quelli del progetto e della sessione.
