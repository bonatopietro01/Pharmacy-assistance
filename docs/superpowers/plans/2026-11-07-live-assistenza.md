# Assistenza in diretta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolvere la postazione locale in un assistente visivo continuo che mostra trascrizione temporanea, fase, schede motivabili, scorte, offerte esplicite, servizi e diagnostica tecnica.

**Architecture:** Il server Python locale mantiene trascrizione e contesto solo in memoria; Vosk fornisce partial e final al classificatore deterministico, che interroga le fonti SQLite/Markdown senza registrare il testo. Il browser legge snapshot completi con `session_id` e `version`, applica solo versioni crescenti e invia azioni esplicite con `expected_version`; risultati audio e azioni di una sessione superata sono scartati. SQLite conserva solo catalogo demo, offerte e impostazioni pubbliche configurate.

**Tech Stack:** Python 3.14 stdlib `http.server`, SQLite/FTS5, Vosk e sounddevice già presenti, HTML/CSS/JavaScript senza framework.

**Spec:** `docs/PROMPT_IMPLEMENTAZIONE.md` e `docs/TaskState.md`.

## Global Constraints

- Il servizio resta vincolato a `127.0.0.1:8765` e all’avvio esistente `AVVIA_BANCO.cmd`.
- Audio, trascrizione, ipotesi, dati destinatario e traccia della sessione restano in memoria e vengono cancellati a stop, reset o disconnessione.
- Log tecnici non includono testo, audio, identificatori del cliente, token, parametri privati o stack trace con input.
- Fase e destinatario sono correggibili dal farmacista; età, sesso, gravidanza, patologie e terapia non sono dedotti da voce, nome o aspetto.
- La conferma del prodotto richiede azione esplicita del farmacista; rifiuto, menzione e uso passato non confermano una vendita.
- Relazioni sintetiche restano visibilmente demo; contenuti clinici o equivalenze reali richiedono fonte applicabile e revisione.
- Le offerte attive sono limitate a periodo e disponibilità e a criteri commerciali dichiarati; salute e dati demografici non determinano promozioni.
- Fonti di turni e farmacia sono collegamenti configurati; quando manca una fonte non si inventa una risposta né si invia la trascrizione.

## Review Focus

- La revisione di una partial Vosk rimpiazza il solo testo provvisorio e rimuove schede/termini non più sostenuti — test in Task 1.
- Negazioni, uso passato, rifiuto e correzioni non producono conferma — test in Task 1.
- Una sessione terminata o sostituita non può reintrodurre dati o risposte obsolete — test in Task 2.
- Esportazione diagnostica e risposte HTTP non includono testo o profilo anche in caso di input ostile — test in Task 2 e 4.
- Offerte scadute, esaurite o basate su criteri non dichiarati restano nascoste — test in Task 3.

## File Structure

- `backend/conversation.py`: estrazione deterministica di fase, destinatario dichiarato, intento commerciale e span di evidenza in un frammento volatile; span in codepoint Python convertiti dal Backend in offset UTF-16 JavaScript.
- `backend/knowledge.py`: retrieval wiki/catalogo, riferimenti, scorte e relazioni prodotto esplicite.
- `backend/desk.py`: stream Vosk partial/final, stato sessione RAM, API locale, offerte, impostazioni pubbliche e diagnostica.
- `database/003_live_assistenza.sql`: migrazione versionata per disponibilità/beneficio offerte e seed solo sintetico.
- `database/configurazione.json`: soli URL pubblici configurati per sito farmacia e fonte territoriale.
- `frontend/index.html`, `frontend/desk.css`, `frontend/desk.js`: trascrizione e controlli a sinistra; prodotto/scorte, suggerimenti e risposte rapide a destra.
- `frontend/diagnostica.html`, `frontend/diagnostica.js`: stati tecnici, eventi minimizzati e copia filtrata.
- `tests/test_conversation.py`, `tests/test_live_session.py`, `tests/test_offers.py`: casi deterministici e API su database temporanei.
- `frontend/README.md`, `database/README.md`, `wiki/GLOSSARIO.md`, `docs/TaskState.md`: istruzioni e tracciabilità aggiornate.

## Task 1: Interpretazione effimera e retrieval spiegabile

**Files:** AI Engineer creates `backend/conversation.py`, `tests/test_conversation.py`; modifies `wiki/GLOSSARIO.md` and selected `wiki/schede/*.md`. Backend alone owns `backend/knowledge.py`.

**Interface:** `analyze(text: str, partial: bool = False) -> dict` returns phase candidate, missing question, declared recipient fields, commercial intent, correction/refusal/past flags and exact evidence spans in Python codepoint offsets. It must not persist or infer an unknown demographic field. `search()` returns cards with source, matching text spans, rule reason and only explicitly linked products.

- [x] Add cases for partial revisions, negation, past use, refusal, correction, service questions, explicitly declared recipient and product-specific commercial intent; verify expected failures.
- [x] Implement minimal deterministic extraction and retrieval against existing catalog/wikis.
- [x] Keep treatment suggestions tied to published reviewed pages; keep demo associations labeled.
- [x] Run focused Python unit cases and inspect the returned spans/source/reason.

## Task 2: Sessione volatile, streaming e API

**Files:** Modify `backend/desk.py`; create `tests/test_live_session.py`.

**Interface:** `/api/stato` returns a complete volatile snapshot: `schema_version`, `session_id`, increasing `version`, microphone/error state, transcript revision/final segments/replaceable partial, phase/source/reason/missing fields, recipient/source, evidence spans/reasons/source, cards, candidate/selected/confirmed product, offers, stock, service and restock. Mutations go through `/api/azione` with `{session_id, expected_version, action, payload}`; stale IDs and versions are rejected without applying the action. The browser consumes only increasing snapshots for its current session. Vosk partials refresh only the partial; finals append a bounded segment. Python codepoint offsets are converted to JavaScript UTF-16 offsets and carry `transcript_revision`. Context cards require both configurable minimum elapsed time (default 3s) and stable evidence; one newest context revision wins. A 12-second server inactivity lease stops and clears an abandoned session.

- [x] Test session reset, partial replacement, final segment retention in RAM, 3-second gate, stable evidence and stale revision rejection.
- [x] Use Vosk `PartialResult()` on the existing audio chunks and retain current `AcceptWaveform()/Result()` final handling.
- [x] Add one in-memory session version, lock-protected action state, reset/disconnect clearing, and same-origin route validation.
- [x] Extend diagnostics with duration and fixed codes only; test that private marker text never appears in event output.
- [x] Run focused Python tests with injected recognizer/audio data (no live client speech in this test).

## Task 3: Offerte e configurazione dei collegamenti pubblici

**Files:** Create `database/003_live_assistenza.sql`, `database/configurazione.json`, `tests/test_offers.py`; modify `backend/desk.py`, `database/README.md`.

**Interface:** `active_offers(today, explicit_interests)` returns only active rows whose validity includes `today`, available quantity is positive, and declared product interest matches exact product/category terms. Offer writes validate product, integer cents, period, quantity and non-empty commercial criterion. Local configuration stores source URLs and a minimum context delay (default 3 seconds); the UI opens a configured public source using only operator-entered commune/date when the configured template supports them. No transcript-derived fields are sent or used to build a URL.

- [x] Test active, expired, out-of-stock, unmatched and explicitly matched offers on a temporary SQLite database.
- [x] Apply the versioned schema migration to a copy first and verify foreign keys and integrity.
- [x] Add local APIs for CRUD minima delle offerte and public-source configuration; apply the verified migration to the demo catalog.
- [x] Confirm synthetic offer and product relations remain marked as demo.

## Task 4: Schermata operativa e diagnostica

**Files:** Modify `frontend/index.html`, `frontend/desk.css`, `frontend/desk.js`, `frontend/diagnostica.html`, `frontend/diagnostica.js`.

**Interface:** The frontend polls at most one snapshot request at a time, renders only increasing `version`, highlights server-provided offsets safely with DOM nodes, and sends explicit actions for phase, recipient, product confirmation, reset, offer management and service fields. It never persists transcript/session state in local storage, URLs, or logs.

- [x] Implement left live transcript/provisional text, evidence details, phase/reason/missing field and manual controls.
- [x] Implement product illustration/name/package/principle/stock and source-checked equivalent display; show complementary items only after confirmation.
- [x] Implement quick answers, active-offer management and configured public links without sending transcript text.
- [x] Implement diagnostic status cards and safe filtered event copy/export.
- [x] Run JavaScript syntax checks and local HTTP integration scenarios. Browser rendering was attempted but not observed because the Windows automation helper could not reselect one unique Chrome window.

## Task 5: Integrazione, documentazione e prova finale

**Files:** Modify `docs/TaskState.md`, `frontend/README.md`, `database/README.md`, `wiki/SCENARI_E_FONTI.md`, `wiki/GLOSSARIO.md`.

- [x] Use the prompt scenarios for continuous synthetic speech events, the 3-second first-card delay, correction, recipient declaration, confirmed products, stock/equivalent rules, offers, service source absence, microphone loss and reset.
- [x] Measure elapsed time to first eligible card and to removal after correction in the synthetic harness; report the values and test conditions.
- [x] Verify SQLite integrity and no transcript marker in the session/database/diagnostic paths exercised by the synthetic tests and HTTP smoke check.
- [x] Update requirement evidence, commands, runtime boundaries, source configuration and remaining unverified items.

