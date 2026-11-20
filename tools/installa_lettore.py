"""Installa in locale la libreria ZXing per leggere QR e DataMatrix dalla telecamera.

    python tools/installa_lettore.py            (o doppio clic su INSTALLA_LETTORE.cmd)
    python tools/installa_lettore.py --verifica (controlla il file già installato)

Scarica `@zxing/library` in versione fissata dal registro npm, verifica il pacchetto con
l'impronta sha512 pubblicata dal registro (`dist.integrity`) e, se è impostata, con
l'impronta SHA-256 fissata qui sotto. Copia solo `umd/index.min.js` in
`frontend/vendor/zxing.min.js` con la licenza Apache-2.0 e registra la SHA-256 del file
in `frontend/vendor/zxing.sha256`. Il banco serve il file in locale: nessuna CDN.

Senza questo file la telecamera legge comunque EAN-13, EAN-8 e il bollino AIC (Code 32)
con il lettore integrato `frontend/barcode1d.js`.
"""

import argparse
import base64
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "frontend" / "vendor"
PACKAGE = "@zxing/library"
VERSION = "0.21.3"
# SHA-256 di umd/index.min.js per questa versione. Vuota finché non è stata verificata la prima
# installazione: lo script la stampa; copiarla qui la rende obbligatoria nelle installazioni successive.
PINNED_SHA256 = ""
MAX_BYTES = 30_000_000


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "sales-agents-installer"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise RuntimeError("Risposta troppo grande.")
    return data


def install():
    meta = json.loads(_get(f"https://registry.npmjs.org/{PACKAGE}/{VERSION}"))
    if meta.get("version") != VERSION or meta.get("license") != "Apache-2.0":
        raise RuntimeError("Metadati del pacchetto inattesi.")
    tarball, integrity = meta["dist"]["tarball"], meta["dist"]["integrity"]
    if not tarball.startswith("https://registry.npmjs.org/") or not integrity.startswith("sha512-"):
        raise RuntimeError("Indirizzo o impronta del pacchetto inattesi.")
    data = _get(tarball)
    digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if "sha512-" + digest != integrity:
        raise RuntimeError("Il pacchetto non corrisponde all'impronta pubblicata dal registro npm.")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        script = archive.extractfile("package/umd/index.min.js").read()
        try:
            license_text = archive.extractfile("package/LICENSE").read()
        except KeyError:
            license_text = b"Apache License 2.0 - https://github.com/zxing-js/library/blob/master/LICENSE\n"
    sha256 = hashlib.sha256(script).hexdigest()
    if PINNED_SHA256 and sha256 != PINNED_SHA256:
        raise RuntimeError("La libreria non corrisponde all'impronta SHA-256 fissata nello script.")
    VENDOR.mkdir(parents=True, exist_ok=True)
    (VENDOR / "zxing.min.js").write_bytes(script)
    (VENDOR / "ZXING_LICENSE.txt").write_bytes(license_text)
    (VENDOR / "zxing.sha256").write_text(f"{sha256}  zxing.min.js  {PACKAGE}@{VERSION}\n", encoding="utf-8")
    return sha256


def verify():
    target = VENDOR / "zxing.min.js"
    record = VENDOR / "zxing.sha256"
    if not target.is_file() or not record.is_file():
        return False, "Libreria non installata."
    expected = PINNED_SHA256 or record.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    return actual == expected, ("OK" if actual == expected else "Il file è cambiato dall'installazione.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Installa il lettore QR/DataMatrix locale (ZXing).")
    parser.add_argument("--verifica", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verifica:
            ok, message = verify()
            print(message)
            return 0 if ok else 1
        sha256 = install()
        print(f"Installato {PACKAGE}@{VERSION} in frontend/vendor/zxing.min.js")
        print(f"SHA-256: {sha256}")
        if not PINNED_SHA256:
            print("Per fissarla, copia questa impronta in PINNED_SHA256 in tools/installa_lettore.py.")
        return 0
    except (OSError, RuntimeError, KeyError, ValueError, tarfile.TarError) as error:
        print(f"Installazione non riuscita: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
