# Wiki della farmacia di prova

Prodotti fittizi con prezzi e scorte simulati. Vista generata da `catalogo.sql`.

| Codice | Prodotto | Categoria | Formato | Prezzo | Disponibilità |
|---|---|---|---|---:|---:|
| DEMO-OTC-01 | Banco Demo A | Farmaco da banco | Spray | € 7,90 | 12 |
| DEMO-OTC-02 | Banco Demo B | Farmaco da banco | Compresse | € 9,80 | 4 |
| DEMO-OTC-03 | Banco Demo C | Farmaco da banco | Soluzione orale | € 11,50 | Non disponibile |
| DEMO-INT-01 | Integratore Demo A | Integratore | Capsule | € 12,90 | 8 |
| DEMO-INT-02 | Integratore Demo B | Integratore | Bustine | € 14,50 | 3 |
| DEMO-INT-03 | Integratore Demo C | Integratore | Gommose | € 10,90 | 6 |

## Scheda Banco Demo A

Codice catalogo `DEMO-OTC-01`.

Scheda di prova per una confezione spray. Nel dialogo, il cliente la cita come prodotto già utilizzato. La scheda serve a mostrare come il sistema riconosce un riferimento passato.

## Scheda Banco Demo B

Codice catalogo `DEMO-OTC-02`.

Scheda di prova per una confezione di compresse. Nel dialogo, il farmacista sceglie di aprirla per consultare insieme la scheda e la disponibilità di magazzino.

## Scheda Banco Demo C

Codice catalogo `DEMO-OTC-03`.

Scheda di prova per una soluzione orale. Le scorte simulate sono a zero. Il caso permette di controllare che sullo schermo compaia la disponibilità corretta.

## Scheda Integratore Demo A

Codice catalogo `DEMO-INT-01`.

Scheda anagrafica di prova per un integratore in capsule. Il catalogo fornisce formato, prezzo e quantità disponibili per la consultazione.

## Scheda Integratore Demo B

Codice catalogo `DEMO-INT-02`.

Scheda anagrafica di prova per un integratore in bustine. Il record permette di filtrare il catalogo per categoria e formato.

## Scheda Integratore Demo C

Codice catalogo `DEMO-INT-03`.

Scheda anagrafica di prova per un integratore in formato gommoso. Il nome simile a quello di altri record aiuta a verificare che la ricerca apra la scheda selezionata.

## Dialogo di prova sul raffreddore

Il cliente dice «Ho il raffreddore e ho già usato Banco Demo A». Il farmacista dice «Apro la scheda di Banco Demo B», poi «Mi correggo, chiudi la scheda B e apri la C». L'esempio riguarda prodotti fittizi e mette in evidenza uso passato, apertura di una scheda e correzione.

## Lettura della disponibilità

La quantità rappresenta le unità disponibili nel catalogo di prova. Quando vale zero, la scheda indica «Non disponibile». Una nuova ricerca può aprire un altro prodotto per consultazione.
