# Installazione Codex nel progetto

Prerequisito: Python 3.11 o successivo, senza librerie esterne. Verifica l’interprete disponibile; se manca, segnala il prerequisito. Non installarlo automaticamente.

Dalla radice di Sales Agents, con percorsi fra virgolette:

```powershell
python "agent-kit/source/Skills/agent-configuration/scripts/install_agent_pack.py" --pack "agent-kit/source" --project "."
python "agent-kit/source/Skills/agent-configuration/scripts/install_agent_pack.py" --pack "agent-kit/source" --project "." --apply
python "agent-kit/source/Skills/agent-configuration/scripts/install_agent_pack.py" --pack "agent-kit/source" --project "." --check
```

L’anteprima e `--check` non scrivono. Risolvi i conflitti prima di `--apply`. Il generatore crea i ruoli in `.codex/agents/`, le skills complete in `.agents/skills/`, `agent-kit/WORKFLOW.md` e il blocco delimitato di coordinamento in `AGENTS.md`. Non installa configurazioni globali o agenti nel runtime dell’applicazione.

`pack.json` è la fonte autorevole degli ID e delle skills. `roles.json` associa ogni nome registrato alla specifica canonica, descrizione e permessi del ruolo. Il manifest `agent-kit/INSTALLATION.json` conserva percorsi, proprietari, fonti e SHA-256 senza percorsi assoluti dell’autore.

Il generatore preserva personalizzazioni e segnala conflitti; non sovrascrive file diversi né cancella automaticamente risorse rimosse dalla fonte. Una migrazione esplicita può rimuovere copie gestite solo dopo aver confrontato i loro hash con il manifest e verificato che non contengano file estranei.

Il controllo statico prova formati, collegamenti, dipendenze e hash. Non dimostra che il client Codex riconosca o invochi i ruoli e le skills. Per questi passaggi segui [runtime-check](runtime-check.md).
