const $ = id => document.getElementById(id);
const allowCodes = new Map([
  ["audio", new Set(["avvio", "attivo", "dipendenze_o_modello", "microfono_o_ricerca", "sessione_chiusa", "lease_scaduta", "trascrizione_non_disponibile"])],
  ["backend", new Set(["operazione_non_disponibile"])],
  ["ricerca", new Set(["ricerca_non_disponibile"])],
  ["telecamera", new Set(["lettura_trovato", "lettura_multipli", "lettura_aifa", "lettura_sconosciuto", "lettura_nessuno"])],
  ["frontend", new Set(["ricerca", "stato", "microfono", "pagina", "azione", "offerte", "configurazione"])]
]);
const allowLevels = new Set(["info", "errore", "avviso"]);
const microphones = new Map([["avvio", "In avvio"], ["attivo", "Attivo"], ["spento", "Spento"], ["errore", "Errore"]]);
const searchStates = new Map([["disponibile", "Disponibile"], ["non_disponibile", "Non disponibile"], ["errore", "Errore recente"]]);
let rows = [];
let refreshing = false;

function element(tag, text) {
  const item = document.createElement(tag);
  item.textContent = text ?? "";
  return item;
}

function presence(value, yes = "Presente", no = "Assente") {
  return value === true ? yes : value === false ? no : "Stato non disponibile";
}

const importNames = new Map([["aifa", "Import AIFA"], ["gestionale", "Import gestionale"]]);
const importOutcomes = new Map([["ok", "Riuscito"], ["parziale", "Parziale"], ["errore", "Errore"]]);
const semanticStates = new Map([["spenta", "Spenta (impostazione)"], ["attiva", "Attiva"],
  ["non_disponibile", "Non disponibile: pacchetto o modello mancante"]]);

function semanticLabel(value) {
  return semanticStates.get(value) || "Stato non disponibile";
}

function importRows(items) {
  const known = new Map((Array.isArray(items) ? items : []).filter(item => importNames.has(item?.fonte))
    .map(item => [item.fonte, item]));
  return [...importNames].map(([key, label]) => {
    const item = known.get(key);
    if (!item) return [label, "Mai eseguito"];
    const when = typeof item.eseguito_il === "string" ? item.eseguito_il.slice(0, 16).replace("T", " ") : "";
    const counts = [item.righe_applicate, item.righe_rifiutate].every(Number.isSafeInteger)
      ? ` · ${item.righe_applicate} applicate, ${item.righe_rifiutate} rifiutate` : "";
    return [label, `${importOutcomes.get(item.esito) || "Esito sconosciuto"} · ${when}${counts}`];
  });
}

const cameraOutcomes = new Map([["trovato", "farmaco trovato"], ["multipli", "più farmaci"],
  ["aifa", "solo in anagrafica AIFA"], ["sconosciuto", "codice non trovato"], ["nessuno", "nessun risultato"]]);
function cameraLabel(value) {
  if (!value?.ultima_lettura) return "Nessuna lettura da quando il banco è avviato";
  const readers = {nativo: "lettore del browser", zxing: "ZXing locale", integrato: "lettore integrato (EAN/AIC)"};
  return "Ultima lettura " + new Date(value.ultima_lettura).toLocaleString("it-IT") + " · "
    + (cameraOutcomes.get(value.esito) || "esito sconosciuto") + (readers[value.lettore] ? " · " + readers[value.lettore] : "");
}

function statuses(data) {
  return [
    ["Backend", data ? "Raggiungibile" : "Non raggiungibile"],
    ["Interfaccia", data?.frontend === "presente" ? "Schermata del banco presente"
      : data?.frontend === "assente" ? "Schermata del banco assente" : "Pagina diagnostica caricata"],
    ["Microfono", microphones.get(data?.microfono) || "Stato non disponibile"],
    ["Modello Vosk", presence(data?.modello_presente)],
    ["Catalogo SQLite", presence(data?.catalogo_presente)],
    ["Ricerca locale", searchStates.get(data?.ricerca) || "Stato non disponibile"],
    ...[["turni", "Fonte turni"], ["orari", "Fonte orari"], ["sito", "Sito farmacia"]].map(([kind, label]) =>
      [label, presence(data?.fonti?.[kind], "Configurata · da verificare", "Non configurata")]),
    ["Ricerca semantica", semanticLabel(data?.ricerca_semantica)],
    ["Telecamera (scheda farmaco)", cameraLabel(data?.telecamera)],
    ["Controllo ogni 3 parole chiave", data?.controllo ? data.controllo.controlli + " controlli · "
      + (data.controllo.modello_attivo ? "agente modello acceso" : "solo verificatore locale")
      + (data.controllo.agente ? " · ultimo agente: " + data.controllo.agente : "") : "—"],
    ...importRows(data?.import)
  ];
}

function safeRows(events) {
  return (Array.isArray(events) ? events : []).flatMap(event => {
    if (!allowCodes.get(event?.componente)?.has(event.codice) || !allowLevels.has(event.livello)) return [];
    if (typeof event.ora !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|\+00:00)$/.test(event.ora)) return [];
    if (!Number.isSafeInteger(event.durata_ms) || event.durata_ms < 0) return [];
    return [[event.ora, event.livello, event.componente, event.codice, event.durata_ms + " ms"]];
  });
}

function render(data) {
  $("components").replaceChildren(...statuses(data).map(([name, value]) => {
    const group = element("div");
    group.append(element("dt", name), element("dd", value));
    return group;
  }));
  rows = safeRows(data?.eventi);
  const tableRows = rows.map(values => {
    const tr = element("tr");
    tr.append(...values.map(value => element("td", value)));
    return tr;
  });
  if (!tableRows.length) {
    const tr = element("tr");
    const td = element("td", "Nessun evento tecnico disponibile.");
    td.colSpan = 5;
    tr.append(td);
    tableRows.push(tr);
  }
  $("events").replaceChildren(...tableRows);
  $("copy").disabled = !rows.length;
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  $("refresh").disabled = true;
  $("copy").disabled = true;
  $("feedback").textContent = "";
  try {
    const response = await fetch("/api/diagnostica", {cache: "no-store", signal: AbortSignal.timeout(6000)});
    if (!response.ok) throw new Error("diagnostic");
    const data = await response.json();
    render(data);
    $("check").textContent = "Controllo del server completato.";
  } catch {
    render(null);
    $("check").textContent = "Verifica che la finestra di avvio del banco sia aperta.";
  } finally {
    refreshing = false;
    $("refresh").disabled = false;
  }
}

$("refresh").addEventListener("click", refresh);
$("copy").addEventListener("click", async () => {
  if (!rows.length) return;
  const exportText = [["Ora (UTC)", "Livello", "Componente", "Codice", "Durata"], ...rows].map(row => row.join("\t")).join("\n");
  try {
    await navigator.clipboard.writeText(exportText);
    $("feedback").textContent = "Eventi tecnici copiati.";
  } catch {
    $("feedback").textContent = "Copia non disponibile. Puoi selezionare e copiare la tabella.";
  }
});
refresh();
