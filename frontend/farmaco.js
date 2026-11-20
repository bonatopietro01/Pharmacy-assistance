"use strict";
// Scheda farmaco: cerca/scansiona, consulta, aggiorna, chiedi. Solo il testo dei codici va al server.

const $ = id => document.getElementById(id);
const list = value => Array.isArray(value) ? value : [];
const euro = new Intl.NumberFormat("it-IT", {style: "currency", currency: "EUR"});
const REVIEWER_KEY = "scheda.revisore";
let current = null;      // the sheet on screen
let pendingAifa = null;  // AIFA row waiting for confirmation

function node(tag, text = "", style) {
  const item = document.createElement(tag);
  item.textContent = text ?? "";
  if (style) item.className = style;
  return item;
}

function say(text, kind = "") {
  $("message").textContent = text || "";
  $("message").dataset.kind = kind;
}

async function post(route, body) {
  const response = await fetch("/api/farmaco/" + route, {
    method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    signal: AbortSignal.timeout(20000)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.errore || "Operazione non riuscita.");
  return data;
}

async function get(route, code) {
  const response = await fetch("/api/farmaco/" + route + "?code=" + encodeURIComponent(code), {cache: "no-store"});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.errore || "Dati non disponibili.");
  return data;
}

function reviewer() {
  const value = $("reviewer").value.trim();
  if (value) { try { localStorage.setItem(REVIEWER_KEY, value); } catch { /* memory only */ } return value; }
  const name = (prompt("Il tuo nome, per il registro delle modifiche:") || "").trim().slice(0, 80);
  if (name) { $("reviewer").value = name; try { localStorage.setItem(REVIEWER_KEY, name); } catch { /* memory only */ } }
  return name;
}

function sourceText(field) {
  const source = field?.source;
  if (!source) return field?.value === null || field?.value === undefined ? "" : "da verificare · nessuna fonte";
  return [source.titolo, field.date || source.consultata_il].filter(Boolean).join(" · ");
}

function sourceNode(field) {
  const box = node("span", "", field?.da_verificare ? "field-source warn" : "field-source");
  if (field?.value === null || field?.value === undefined || field?.value === "") return box;
  const text = sourceText(field);
  if (field?.source?.url && /^https:\/\//.test(field.source.url)) {
    const link = node("a", text);
    link.href = field.source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    box.append(link);
  } else {
    box.textContent = text;
  }
  return box;
}

function valueText(field) {
  if (field.value === null || field.value === undefined || field.value === "") return "—";
  if (field.label.startsWith("Prezzo")) return euro.format(field.value / 100);
  return String(field.value);
}

function fieldsBlock(title, fields) {
  const section = node("section", "", "info-block");
  section.append(node("h3", title));
  const dl = node("dl", "", "fields");
  for (const field of fields) {
    dl.append(node("dt", field.label));
    const dd = node("dd");
    dd.append(node("span", valueText(field)), sourceNode(field));
    dl.append(dd);
  }
  section.append(dl);
  return section;
}

// ---------- search & scan ----------

async function lookup(text, origin = "manuale", reader = null) {
  say("");
  for (const id of ["matches-box", "aifa-box", "manual-box"]) $(id).hidden = true;
  let result;
  try {
    result = await post(origin === "telecamera" ? "codice" : "cerca",
      origin === "telecamera" ? {codice: text, origine: "telecamera", lettore: reader || "sconosciuto"} : {testo: text});
  } catch (error) { return say(error.message, "error"); }
  const parsed = result.parsed || {};
  if (origin === "telecamera") showLastRead(text, result.status);
  if (parsed.valid === false) say("Cifra di controllo non valida: il codice potrebbe essere letto male.", "warn");
  if (result.status === "trovato") return openSheet(result.products[0].code);
  if (result.status === "multipli") return showMatches(result.products);
  if (result.status === "aifa") return showAifa(result.aifa);
  if (result.status === "sconosciuto") return showManual(parsed.value);
  if (parsed.kind === "url") return say("Il QR contiene un indirizzo, non un codice prodotto: " + parsed.value, "warn");
  say("Nessun farmaco trovato. Prova con il nome o il principio attivo.", "warn");
}

function showMatches(products) {
  $("matches-box").hidden = false;
  $("matches").replaceChildren(...products.map(item => {
    const li = node("li");
    const button = node("button", "", "match");
    button.type = "button";
    button.append(node("strong", item.name),
      node("span", [item.form, item.active, item.aic ? "AIC " + item.aic : null,
        item.review === "da_revisionare" ? "da revisionare" : null].filter(Boolean).join(" · "), "result-facts"));
    button.addEventListener("click", () => openSheet(item.code));
    li.append(button);
    return li;
  }));
}

function showAifa(row) {
  pendingAifa = row;
  $("aifa-box").hidden = false;
  const labels = [["denominazione", "Denominazione"], ["descrizione", "Confezione"], ["aic", "AIC"],
    ["principio", "Principio attivo"], ["atc", "ATC"], ["fornitura", "Fornitura"], ["regime", "Regime"],
    ["ditta", "Titolare"], ["stato", "Stato"]];
  const items = [];
  for (const [key, label] of labels) {
    if (!row?.[key]) continue;
    items.push(node("dt", label), node("dd", row[key]));
  }
  $("aifa-fields").replaceChildren(...items);
}

function showManual(code) {
  $("manual-box").hidden = false;
  $("manual-code").value = code || "";
}

$("search-form").addEventListener("submit", event => {
  event.preventDefault();
  const text = $("query").value.trim();
  if (text) lookup(text);
});

let cameraReader = null;
function cameraStatus(text, state, reader) {
  cameraReader = reader || cameraReader;
  $("camera-status").textContent = text;
  $("camera-status").dataset.state = state;
  if (state !== "on") {
    setTimeout(() => { if (!Scanner.isActive()) $("camera-box").hidden = true; }, state === "error" ? 8000 : 3000);
  }
}

function showLastRead(code, outcome) {
  const kind = /^A?\d{9}$/.test(code) ? "AIC" : /^\d{8,14}$/.test(code) ? "EAN" : "codice";
  const tail = code.replace(/\s/g, "").slice(-4);
  const outcomes = {trovato: "trovato", multipli: "più risultati", aifa: "solo in anagrafica AIFA",
    sconosciuto: "non trovato", nessuno: "non trovato"};
  $("last-read").textContent = "Letto: " + kind + " …" + tail + " · " + (outcomes[outcome] || outcome);
  $("last-read").hidden = false;
  clearTimeout(showLastRead.timer);
  showLastRead.timer = setTimeout(() => { $("last-read").hidden = true; }, 5000);
}

async function scan() {
  if (Scanner.isActive()) { Scanner.stop($("camera")); $("camera-box").hidden = true; return; }
  $("camera-box").hidden = false;
  $("camera-box").classList.remove("minimized");
  $("camera-status").textContent = "Avvio telecamera…";
  await Scanner.start($("camera"), (code, reader) => {
    $("camera-box").hidden = true;
    lookup(code, "telecamera", reader);
  }, cameraStatus);
}
$("scan").addEventListener("click", scan);
$("camera-stop").addEventListener("click", () => { Scanner.stop($("camera")); $("camera-box").hidden = true; });
$("camera-min").addEventListener("click", () => $("camera-box").classList.toggle("minimized"));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && Scanner.isActive()) {
    Scanner.stop($("camera"));
    $("camera-box").hidden = true;
    return;
  }
  if (event.key.toLowerCase() !== "q" || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest("input, textarea, select")) return;
  event.preventDefault();
  scan();
});

$("aifa-add").addEventListener("click", async () => {
  const name = reviewer();
  if (!name || !pendingAifa) return;
  try {
    const added = await post("aggiungi", {aic: pendingAifa.aic, revisore: name});
    say("Aggiunto come «da revisionare»: inserisci prezzo e giacenza dalla scheda.", "ok");
    $("aifa-box").hidden = true;
    openSheet(added.code);
  } catch (error) { say(error.message, "error"); }
});

$("manual-form").addEventListener("submit", async event => {
  event.preventDefault();
  const name = reviewer();
  if (!name) return;
  const campi = Object.fromEntries(new FormData($("manual-form")));
  try {
    const added = await post("aggiungi", {campi, revisore: name});
    $("manual-box").hidden = true;
    openSheet(added.code);
  } catch (error) { say(error.message, "error"); }
});

// ---------- sheet ----------

async function openSheet(code) {
  for (const id of ["matches-box", "aifa-box", "manual-box"]) $(id).hidden = true;
  try {
    current = await get("scheda", code);
  } catch (error) { return say(error.message, "error"); }
  $("sheet").hidden = false;
  $("sheet-name").textContent = current.name;
  const meta = [current.code, current.review === "da_revisionare" ? "da revisionare" : current.review,
    current.proponibile_al_banco ? "consultabile al banco" : "non ancora proposto al banco (dati da verificare)"];
  $("sheet-meta").textContent = meta.filter(Boolean).join(" · ");
  $("sheet-image").hidden = !current.image;
  if (current.image) {
    $("sheet-image").src = current.image;
    $("sheet-image").title = current.image_source?.titolo || "";
  }
  $("show-desk").disabled = !current.banco_attivo || !current.proponibile_al_banco;
  $("show-desk").title = !current.banco_attivo ? "Nessuna sessione attiva al banco"
    : !current.proponibile_al_banco ? "Il farmaco non è ancora consultabile al banco" : "Seleziona il farmaco al banco (non conferma)";
  $("answer").replaceChildren();
  renderInfo();
  selectTab("tab-info");
  history.replaceState(null, "", "/farmaco#" + encodeURIComponent(code));
}

function renderInfo() {
  const panel = $("panel-info");
  const blocks = [fieldsBlock("Identità", current.identita), fieldsBlock("Ammissibilità", current.ammissibilita),
    fieldsBlock("Vendita", current.vendita)];
  const needs = node("section", "", "info-block");
  needs.append(node("h3", "Bisogni collegati"));
  const ul = node("ul", "", "plain-list");
  for (const item of list(current.bisogni)) {
    const li = node("li");
    li.append(node("strong", item.nome), node("span", " · " + item.stato_revisione, item.stato_revisione === "approvata" ? "" : "warn-text"));
    if (item.source?.titolo) li.append(node("span", " · " + item.source.titolo, "field-source"));
    ul.append(li);
  }
  if (!ul.childElementCount) ul.append(node("li", "Nessun bisogno collegato nelle fonti.", "result-state"));
  needs.append(ul);
  const populations = node("section", "", "info-block");
  populations.append(node("h3", "Per chi è (popolazioni)"));
  const popList = node("ul", "", "plain-list");
  const months = value => value === null || value === undefined ? null
    : value % 12 === 0 ? value / 12 + " anni" : value + " mesi";
  for (const item of list(current.popolazioni)) {
    const range = [months(item.eta_min_mesi) && "da " + months(item.eta_min_mesi),
      months(item.eta_max_mesi) && "fino a " + months(item.eta_max_mesi)].filter(Boolean).join(" ");
    const li = node("li");
    li.append(node("strong", item.popolazione + (range ? " (" + range + ")" : "")),
      node("span", " · " + item.esito.replace("_", " "), ["controindicato", "sconsigliato"].includes(item.esito) ? "warn-text" : ""),
      node("span", " · " + item.stato_revisione + (item.nota ? " · " + item.nota : ""), "field-source"));
    if (item.source?.titolo) li.append(node("span", " · " + item.source.titolo, "field-source"));
    popList.append(li);
  }
  if (!popList.childElementCount) popList.append(node("li", "Nessun dato per popolazione registrato.", "result-state"));
  populations.append(popList);
  const variants = node("section", "", "info-block");
  variants.append(node("h3", "Varianti documentate"));
  variants.append(node("p", list(current.varianti).map(item => item.label || item.code).join(" · ") || "Nessuna variante documentata.",
    "result-facts"));
  const aliases = list(current.alias);
  if (aliases.length) variants.append(node("p", "Alias: " + aliases.map(item => item.alias
    + (item.stato_revisione !== "approvata" ? " (" + item.stato_revisione + ")" : "")).join(" · "), "result-facts"));
  const wiki = node("section", "", "info-block wiki-block");
  wiki.append(node("h3", "Wiki" + (current.wiki?.page ? " · " + current.wiki.page : "")));
  wiki.append(node("pre", current.wiki?.text || "Nessuna pagina wiki.", "wiki-text"));
  panel.replaceChildren(...blocks, needs, populations, variants, wiki);
}

const levelNames = {1: "Abbinamento approvato", 2: "Approvato per il bisogno", 3: "Stesso bisogno · non revisionato"};

async function renderConsigli() {
  const panel = $("panel-consigli");
  panel.replaceChildren(node("p", "Caricamento…", "result-state"));
  let data;
  try { data = await get("consigli", current.code); } catch (error) { return panel.replaceChildren(node("p", error.message, "message")); }
  const blocks = [];
  const linked = node("section", "", "info-block");
  linked.append(node("h3", "Integratori collegati"));
  for (const item of list(data.integratori)) {
    const card = node("article", "", "linked-card" + (item.level < 3 ? " focus" : ""));
    const head = node("div", "", "card-line");
    head.append(node("strong", item.name, "card-name truncate"),
      node("span", Number.isInteger(item.price_cents) ? euro.format(item.price_cents / 100) : "—", "card-price"));
    card.append(head);
    const labels = node("span", "", "row-labels");
    labels.append(node("span", levelNames[item.level] || item.level_label, item.level >= 3 ? "label warn" : "label"));
    if (Number.isInteger(item.stock)) labels.append(node("span", "giacenza " + item.stock, "label"));
    card.append(labels, node("span", item.linked_to?.[0]?.motivo || "", "rank-reason"));
    linked.append(card);
  }
  if (!list(data.integratori).length) linked.append(node("p", "Nessun integratore collegato nelle fonti registrate.", "result-state"));
  blocks.push(linked);
  if (list(data.proposte_in_revisione).length) {
    const pending = node("section", "", "info-block");
    pending.append(node("h3", "Proposte in attesa di revisione"));
    pending.append(node("p", data.proposte_in_revisione.map(item => item.name).join(" · "), "result-facts"));
    blocks.push(pending);
  }
  const offers = node("section", "", "info-block");
  offers.append(node("h3", "Offerte attive"));
  offers.append(node("p", list(data.offerte).map(item => [item.title, item.benefit, item.end ? "fino al " + item.end : null]
    .filter(Boolean).join(" · ")).join(" | ") || "Nessuna offerta attiva.", "result-facts"));
  blocks.push(offers);
  const create = node("form", "", "info-block settings-form propose-form");
  create.id = "offer-form";
  create.append(node("h3", "Crea offerta su questo prodotto"),
    node("p", "Comparirà al banco in «Con questo prodotto» quando il farmaco viene scelto.", "note"));
  for (const [name, label, type] of [["titolo", "Titolo (es. Seconda confezione −50%)", "text"],
    ["beneficio", "Beneficio da dire al cliente", "text"], ["prezzo", "Prezzo in offerta (€, facoltativo)", "text"],
    ["inizio", "Dal", "date"], ["fine", "Al", "date"]]) {
    const wrap = node("label", label);
    const input = node("input");
    input.name = name; input.type = type;
    input.required = ["titolo", "inizio", "fine"].includes(name);
    if (name === "inizio") input.value = new Date().toISOString().slice(0, 10);
    wrap.append(input);
    create.append(wrap);
  }
  const createButton = node("button", "Crea offerta", "primary");
  createButton.type = "submit";
  create.append(createButton);
  create.addEventListener("submit", async event => {
    event.preventDefault();
    const name = reviewer();
    if (!name) return;
    const body = Object.fromEntries(new FormData(create));
    const price = String(body.prezzo || "").trim();
    const offerta = {titolo: body.titolo, beneficio: body.beneficio, inizio: body.inizio, fine: body.fine,
      prezzo_cent: price ? Math.round(Number(price.replace(",", ".")) * 100) : null};
    try {
      await post("offerta", {code: current.code, offerta, revisore: name});
      say("Offerta creata: comparirà al banco con questo prodotto.", "ok");
      renderConsigli();
    } catch (error) { say(error.message, "error"); }
  });
  blocks.splice(blocks.indexOf(offers) + 1, 0, create);
  const advice = node("section", "", "info-block");
  advice.append(node("h3", "Consigli dal protocollo di banco"));
  const ul = node("ul", "", "plain-list");
  for (const item of list(data.consigli_protocollo)) ul.append(node("li", item.text + " (protocollo " + item.concept + " v" + item.version + ")"));
  if (!ul.childElementCount) ul.append(node("li", "Nessun protocollo approvato per i bisogni di questo farmaco.", "result-state"));
  advice.append(ul);
  blocks.push(advice);
  const propose = node("form", "", "info-block settings-form propose-form");
  propose.append(node("h3", "Proponi un abbinamento per la revisione"),
    node("p", "Diventa una relazione «candidata»: l'approvazione si fa nella revisione del farmacista responsabile.", "note"));
  const fields = [["integratore", "Codice del prodotto da abbinare (es. REAL-SUP-004)"], ["motivo", "Motivo"],
    ["esclusioni", "Escludere se…"], ["fonte_url", "Fonte (https)"]];
  for (const [name, label] of fields) {
    const wrap = node("label", label);
    const input = node("input");
    input.name = name;
    input.required = true;
    input.maxLength = 300;
    wrap.append(input);
    propose.append(wrap);
  }
  const submit = node("button", "Proponi per revisione", "primary");
  submit.type = "submit";
  propose.append(submit);
  propose.addEventListener("submit", async event => {
    event.preventDefault();
    const name = reviewer();
    if (!name) return;
    const body = Object.fromEntries(new FormData(propose));
    try {
      await post("proponi", {...body, code: current.code, revisore: name});
      say("Proposta registrata come candidata.", "ok");
      renderConsigli();
    } catch (error) { say(error.message, "error"); }
  });
  blocks.push(propose);
  panel.replaceChildren(...blocks);
}

async function renderStorico() {
  const panel = $("panel-storico");
  panel.replaceChildren(node("p", "Caricamento…", "result-state"));
  let data;
  try { data = await get("storico", current.code); } catch (error) { return panel.replaceChildren(node("p", error.message, "message")); }
  const reviews = node("section", "", "info-block");
  reviews.append(node("h3", "Modifiche e revisioni"));
  const table = node("table", "", "history");
  const head = node("tr");
  for (const label of ["Quando", "Chi", "Cosa", "Prima", "Dopo"]) head.append(node("th", label));
  table.append(head);
  for (const item of list(data.revisioni)) {
    const row = node("tr");
    for (const value of [new Date(item.il).toLocaleString("it-IT"), item.revisore, item.nota || item.chiave,
      item.da_stato || "—", item.a_stato]) row.append(node("td", value));
    table.append(row);
  }
  reviews.append(list(data.revisioni).length ? table : node("p", "Nessuna modifica registrata.", "result-state"));
  const imports = node("section", "", "info-block");
  imports.append(node("h3", "Import"));
  imports.append(node("p", list(data.import).map(item => [item.fonte, item.esito, item.eseguito_il?.slice(0, 10)].join(" · "))
    .join(" | ") || "Nessun import registrato.", "result-facts"));
  const feedback = node("section", "", "info-block");
  feedback.append(node("h3", "Al banco (conteggi anonimi)"));
  const counts = Object.entries(data.feedback || {});
  feedback.append(node("p", counts.map(([event, count]) => event + " " + count).join(" · ") || "Nessun evento.", "result-facts"));
  panel.replaceChildren(reviews, imports, feedback);
}

function selectTab(id) {
  for (const tab of document.querySelectorAll('[role="tab"]')) {
    const on = tab.id === id;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    $(tab.getAttribute("aria-controls")).hidden = !on;
  }
  if (id === "tab-consigli") renderConsigli();
  if (id === "tab-storico") renderStorico();
}
for (const tab of document.querySelectorAll('[role="tab"]')) {
  tab.addEventListener("click", () => selectTab(tab.id));
  tab.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    const next = tabs[(tabs.indexOf(tab) + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    selectTab(next.id);
    next.focus();
  });
}

// ---------- update ----------

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("File non leggibile."));
    reader.readAsDataURL(file);
  });
}

$("update-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData($("update-form"));
  const name = reviewer();
  if (!name || !current) return;
  const changes = {};
  const price = String(form.get("prezzo") || "").trim();
  if (price) changes.prezzo_cent = Math.round(Number(price.replace(",", ".")) * 100);
  const stock = String(form.get("quantita") || "").trim();
  if (stock) changes.quantita = Number(stock);
  const source = String(form.get("fonte_url") || "").trim();
  if (form.get("regime")) changes.regime_fornitura = form.get("regime");
  const age = String(form.get("eta") || "").trim();
  if (age) changes.eta_minima_anni = Number(age);
  if (form.get("verifica")) changes.verifica = form.get("verifica");
  const alias = String(form.get("alias") || "").trim();
  if (alias) changes.alias = {testo: alias, tipo: form.get("alias_tipo")};
  const file = form.get("immagine_file");
  const imageUrl = String(form.get("immagine_url") || "").trim();
  try {
    if (file && file.size) {
      if (file.size > 3000000) throw new Error("Immagine troppo grande (massimo 3 MB).");
      changes.immagine = {data_base64: await readFile(file)};
    } else if (imageUrl) {
      changes.immagine = {url: imageUrl};
    }
    if ((changes.regime_fornitura || "eta_minima_anni" in changes || changes.verifica || changes.immagine) && !source) {
      throw new Error("Regime, età, verifiche e immagini richiedono una fonte https.");
    }
    if (source) changes.fonte_url = source;
    if (!Object.keys(changes).filter(key => key !== "fonte_url").length) throw new Error("Nessuna modifica da salvare.");
    const result = await post("aggiorna", {code: current.code, modifiche: changes, revisore: name});
    $("update-status").textContent = "Salvato: " + (list(result.applicati).join(", ") || "nessun cambiamento");
    const keep = name;
    $("update-form").reset();
    $("reviewer").value = keep;
    await openSheet(current.code);
    selectTab("tab-aggiorna");
  } catch (error) {
    $("update-status").textContent = error.message;
  }
});

// ---------- ask & show at desk ----------

$("ask-form").addEventListener("submit", async event => {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question || !current) return;
  try {
    const data = await post("chiedi", {code: current.code, domanda: question});
    const box = [node("p", data.risposta, "answer-text")];
    const cites = list(data.citazioni);
    if (cites.length) {
      const ul = node("ul", "", "plain-list citations");
      for (const cite of cites) {
        const li = node("li");
        if (cite.url && /^https:\/\//.test(cite.url)) {
          const link = node("a", cite.titolo || cite.url);
          link.href = cite.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          li.append(link);
        } else {
          li.textContent = cite.titolo || "Fonte registrata";
        }
        if (cite.data) li.append(node("span", " · " + cite.data, "field-source"));
        ul.append(li);
      }
      box.push(ul);
    }
    box.push(node("p", data.modo === "modello" ? "Risposta del modello, dai soli dati della scheda." : "Risposta dai dati registrati.", "note"));
    $("answer").replaceChildren(...box);
  } catch (error) {
    $("answer").replaceChildren(node("p", error.message, "message"));
  }
});

$("show-desk").addEventListener("click", async () => {
  if (!current) return;
  try {
    await post("mostra-al-banco", {code: current.code});
    say("Selezionato al banco. La conferma resta al farmacista.", "ok");
  } catch (error) { say(error.message, "error"); }
});

try { $("reviewer").value = localStorage.getItem(REVIEWER_KEY) || ""; } catch { /* memory only */ }
const [initial, wanted] = decodeURIComponent(location.hash.slice(1)).split("&");
if (/^[A-Za-z0-9._-]{1,60}$/.test(initial || "")) {
  openSheet(initial).then(async () => {
    if (wanted === "offerta" && current) {
      selectTab("tab-consigli");
      setTimeout(() => $("offer-form")?.scrollIntoView({block: "start"}), 600);
    }
  });
}
