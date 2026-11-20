# Protocolli di banco

Un protocollo di banco è la scheda che il farmacista vorrebbe avere davanti quando un cliente dice «ho il raffreddore»: cosa chiedere, quando fermarsi e inviare al medico, quali opzioni considerare, cosa proporre in aggiunta e cosa dire alla fine. Oggi la wiki ha schede prodotto (93 «documentate», quasi tutte ricavate dal catalogo) ma nessuna scheda di questo tipo, e il banco non ha nulla da mostrare tra il sintomo riconosciuto e la scelta del prodotto.

## Dove vivono

- Una scheda per concetto in `schede/protocollo-<concetto>.md`, con `tipo = "protocollo"`.
- Lo stato segue le regole della wiki: `bozza` finché il farmacista revisore non l'ha riletta, poi `pubblicata` con `fonte`, `revisore` e `versione`. Una bozza non entra nell'indice del banco.
- Con la migrazione 006 il contenuto approvato si pubblica anche in `protocolli_banco` e `protocollo_voci`, così il banco legge le voci strutturate (domande con il filtro che alimentano, segnali d'allarme, consigli) invece del testo libero.

## Struttura della scheda

```
+++
titolo = "Protocollo · <Concetto>"
tipo = "protocollo"
stato = "bozza"
concetto = "<id del concetto>"
termini = []          # il riconoscimento sta in database/lessico-concetti.json
fonte = ""            # fonte principale (linee guida, RCP dei prodotti collegati)
revisore = ""
versione = ""
+++

## 1. Domande di inquadramento     (max 4, nell'ordine in cui farle)
## 2. Segnali d'allarme → medico    (se presenti: niente vendita, invio)
## 3. Opzioni da considerare        (rimando alle relazioni del catalogo, nessun prodotto inventato)
## 4. Complementi di banco          (supporto e comfort, non clinici; categoria di scaffale o SKU)
## 5. Consigli da dare a voce       (comportamentali, 1 riga ciascuno)
## 6. Follow-up                     (quando tornare o rivolgersi al medico)
```

## Regole

1. Il protocollo non sceglie il prodotto: le opzioni vengono dalle relazioni sintomo-prodotto del catalogo con la loro fonte. Il protocollo aggiunge il contesto per scegliere.
2. Le domande servono ai filtri di ammissibilità (età, gravidanza e allattamento, terapie in corso, patologie, durata): ogni risposta esclude opzioni, non ne aggiunge.
3. I complementi di banco sono proposte di supporto (igiene, dispositivi, comfort, formato). Un abbinamento con effetto clinico (es. integratore con farmaco) resta in `relazioni_prodotti` come `complemento_clinico` e segue la revisione clinica.
4. Massimo una proposta aggiuntiva per cliente: il banco ne mostra una, quella con priorità più alta tra le approvate e disponibili.

Esempio in bozza: [Protocollo · Raffreddore](schede/protocollo-raffreddore.md).
