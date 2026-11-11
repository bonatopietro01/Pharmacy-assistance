# Sales Agents

## Overview

Sales Agents is a local prototype that helps a pharmacist consult product information during a conversation. It uses temporary speech recognition to find relevant entries in a local SQLite catalog and wiki, shown only on the pharmacist's screen.

## Quick start

1. On Windows, run `AVVIA_BANCO.cmd`.
2. If needed, configure the microphone and speech engine in **Impostazioni** (Settings).
3. Select **Inizia ascolto** (Start Listening). The microphone is never activated automatically.

See the [user guide](frontend/README.md) for setup details and instructions for using the desk.

## Data and privacy

This is a demonstration, not a production pharmacy system. The catalog combines documented product records with demo data. Any prices and stock shown come from the local catalog and are not synced with a pharmacy management system. Product information is for the pharmacist to review against its sources.

Audio and recognized text remain in memory and are not written to disk or logs. Speech recognition uses a local engine. If the optional OpenAI phase provider is explicitly enabled, the app sends finalized text fragments and limited evidence for phase classification; it does not send audio. The session contract is listed below.

## Documentation

- [Catalog and product data](database/README.md)
- [Wiki authoring and retrieval](wiki/README.md)
- [Live session contract](docs/CONTRATTO_SESSIONE.md)
