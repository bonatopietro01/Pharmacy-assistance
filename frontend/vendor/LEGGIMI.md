# Lettore codici della Scheda farmaco

La telecamera della pagina **Scheda farmaco** usa, nell'ordine:

1. **Il lettore del browser** (`BarcodeDetector`), se c'è. Su Chrome per Windows di solito non c'è.
2. **ZXing locale**, se installato: legge anche **QR** e **DataMatrix** (GS1, ne usa solo il GTIN).
3. **Il lettore integrato** `frontend/barcode1d.js`: sempre presente, legge **EAN-13**, **EAN-8**
   e il **bollino AIC** (Code 32). Non legge QR e DataMatrix.

## Installare ZXing (una volta)

Doppio clic su `INSTALLA_LETTORE.cmd` nella cartella del progetto (serve internet).
Lo script scarica `@zxing/library` 0.21.3 (licenza Apache-2.0) dal registro npm, lo verifica con
l'impronta pubblicata dal registro, copia `zxing.min.js` qui e registra la sua SHA-256 in
`zxing.sha256`. Controllo successivo: `python tools/installa_lettore.py --verifica`.

Il file è servito dal banco locale (`/vendor/zxing.min.js`): nessuna CDN, la
Content-Security-Policy `default-src 'self'` non cambia. Nessuna immagine della telecamera
viene salvata o inviata: al banco arriva solo il testo del codice.
