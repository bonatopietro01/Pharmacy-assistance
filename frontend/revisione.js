"use strict";
const $ = id => document.getElementById(id);
const REVIEWER_KEY = "scheda.revisore";
const kindNames = {protocollo: "Protocollo", complemento: "Complemento di banco", relazione: "Bisogno → prodotto",
  abbinamento: "Abbinamento", popolazione: "Popolazione"};
const fieldNames = {benefici: "Benefici", rischi: "Rischi / avvertenze", prerequisiti: "Prerequisiti", esclusioni: "Escludere se"};

function node(tag, text = "", style) {
  const item = document.createElement(tag);
  item.textContent = text ?? "";
  if (style) item.className = style;
  return item;
}

async function load() {
  const params = new URLSearchParams();
  if ($("kind").value) params.set("tipo", $("kind").value);
  const concept = $("concept").value.trim();
  if (/^[a-z0-9-]+$/.test(concept)) params.set("concetto", concept);
  const response = await fetch("/api/revisione?" + params, {cache: "no-store"});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) return ($("message").textContent = data.errore || "Coda non disponibile.");
  const items = Array.isArray(data.voci) ? data.voci : [];
  $("count").textContent = items.length + " voci da rivedere";
  $("items").replaceChildren(...items.map(card));
}

function card(item) {
  const box = node("article", "", "review-card");
  const head = node("div", "", "card-line");
  head.append(node("span", kindNames[item.kind] || item.kind, "label"), node("strong", item.title, "card-name"));
  if (item.demand) head.append(node("span", item.demand + " al banco", "label level"));
  box.append(head);
  if (item.detail) box.append(node("p", item.detail, "result-facts"));
  if (item.source?.title) {
    const p = node("p", "Fonte: ", "field-source");
    if (item.source.url && /^https:\/\//.test(item.source.url)) {
      const link = node("a", item.source.title);
      link.href = item.source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      p.append(link);
    } else p.append(item.source.title);
    box.append(p);
  }
  const form = node("form", "", "settings-form review-form");
  for (const [name, value] of Object.entries(item.fields || {})) {
    const label = node("label", fieldNames[name] || name);
    const input = node("textarea");
    input.name = name; input.rows = 2; input.maxLength = 800; input.value = value || "";
    input.required = (item.required || []).includes(name);
    label.append(input);
    form.append(label);
  }
  const note = node("label", "Nota (obbligatoria per respingere)");
  const noteInput = node("input"); noteInput.name = "nota"; noteInput.maxLength = 300;
  note.append(noteInput);
  form.append(note);
  const actions = node("div", "", "dialog-actions");
  for (const [decision, text, style] of [["approva", "Approva", "primary"], ["respingi", "Respingi", ""]]) {
    const button = node("button", text, style); button.type = "button";
    button.addEventListener("click", () => decide(item, decision, form, box));
    actions.append(button);
  }
  const skip = node("button", "Salta"); skip.type = "button";
  skip.addEventListener("click", () => box.remove());
  actions.append(skip);
  form.append(actions);
  box.append(form);
  return box;
}

async function decide(item, decision, form, box) {
  const reviewer = $("reviewer").value.trim();
  if (!reviewer) { $("reviewer").focus(); return ($("message").textContent = "Scrivi il tuo nome prima di decidere."); }
  try { localStorage.setItem(REVIEWER_KEY, reviewer); } catch { /* memory only */ }
  const data = Object.fromEntries(new FormData(form));
  const nota = data.nota || ""; delete data.nota;
  const response = await fetch("/api/revisione/decidi", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({tipo: item.kind, chiave: item.key, decisione: decision, revisore: reviewer, campi: data, nota})});
  const result = await response.json().catch(() => ({}));
  if (!response.ok) return ($("message").textContent = result.errore || "Decisione non salvata.");
  $("message").textContent = (decision === "approva" ? "Approvato: " : "Respinto: ") + item.title;
  box.remove();
}

try { $("reviewer").value = localStorage.getItem(REVIEWER_KEY) || ""; } catch { /* memory only */ }
$("kind").addEventListener("change", load);
$("concept").addEventListener("change", load);
$("filters").addEventListener("submit", event => { event.preventDefault(); load(); });
const initial = new URLSearchParams(location.search);
if (initial.get("concetto")) $("concept").value = initial.get("concetto");
load();
