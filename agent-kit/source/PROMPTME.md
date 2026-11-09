# Installazione e avvio · Codex

Leggi `WORKFLOW.md`, `Skills/README.md` e `Skills/agent-configuration/SKILL.md`. Questo pack configura soltanto Codex: TOML degli agenti in `.codex/agents/`, skills in `.agents/skills/`.

1. Dalla radice del progetto verifica Python 3.11+ e usa il generatore incluso. Se Python manca, segnala il prerequisito senza installarlo automaticamente.

   ```powershell
   python "agent-kit/source/Skills/agent-configuration/scripts/install_agent_pack.py" --pack "agent-kit/source" --project "."
   python "agent-kit/source/Skills/agent-configuration/scripts/install_agent_pack.py" --pack "agent-kit/source" --project "." --apply
   python "agent-kit/source/Skills/agent-configuration/scripts/install_agent_pack.py" --pack "agent-kit/source" --project "." --check
   ```

2. Esamina l’anteprima e risolvi conflitti prima di applicare. Il generatore preserva le personalizzazioni, registra fonti e hash in `agent-kit/INSTALLATION.json` e collega il workflow da `AGENTS.md`.
3. Sono inclusi sette ruoli Sales Agents e le dodici skills dichiarate in `pack.json`. Le istruzioni di PromptAgent, Architect e Reviewer restano in sola lettura; in Codex tutti gli agenti ereditano i permessi della sessione.
4. Distingui file generati, controllo statico, riconoscimento nel catalogo Codex e chiamate effettive. `--check` non prova l’esecuzione di agenti o skills.

La chat principale delega soltanto ai ruoli registrati e supportati dalla sessione. Se un ruolo o una skill necessari non vengono riconosciuti, diagnostica nome, formato, percorso, permessi e ricaricamento prima del lavoro dipendente. Non sostituire una delega mancante con un ruolo recitato nella chat.

Queste configurazioni appartengono all’assistente di coding; non installano agenti nel runtime dell’app Sales Agents. La richiesta concreta e il TaskState governano obiettivo, permessi e controlli.
