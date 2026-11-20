const $ = id => document.getElementById(id);
const list = value => Array.isArray(value) ? value : [];
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;

function node(tag, text = "", style) {
  const item = document.createElement(tag);
  item.textContent = text;
  if (style) item.className = style;
  return item;
}

function bars(rows, label, value, secondary) {
  const max = Math.max(1, ...rows.map(row => Math.max(count(row[value]), secondary ? count(row[secondary]) : 0)));
  if (!rows.length) return [node("p", "Nessun dato nel periodo.", "note")];
  return rows.flatMap(row => {
    const lines = [];
    for (const [key, extra] of [[value, ""], ...(secondary ? [[secondary, "secondary"]] : [])]) {
      const line = node("div", "", "bar-row");
      const name = node("span", key === value ? String(row[label] ?? "") : "", "bar-label");
      name.title = String(row[label] ?? "");
      const bar = node("div", "", "bar " + extra);
      bar.style.width = (100 * count(row[key]) / max) + "%";
      bar.setAttribute("aria-hidden", "true");
      const holder = node("div");
      holder.append(bar);
      line.append(name, holder, node("span", String(count(row[key])) + (extra ? " acc." : ""), "bar-value"));
      lines.push(line);
    }
    return lines;
  });
}

function funnel(rows) {
  if (!rows.length) return [node("p", "Nessun dato nel periodo.", "note")];
  const first = Math.max(1, ...rows.map(row => count(row.n)));
  const out = [];
  rows.forEach((row, index) => {
    if (index > 0) {
      const previous = count(rows[index - 1].n);
      const lost = previous ? Math.round(100 * (previous - count(row.n)) / previous) : 0;
      out.push(node("p", "− " + Math.max(0, lost) + "% al passo successivo", "drop"));
    }
    const line = node("div", "", "bar-row");
    const bar = node("div", "", "bar");
    bar.style.width = (100 * count(row.n) / first) + "%";
    const holder = node("div");
    holder.append(bar);
    line.append(node("span", String(row.passo ?? ""), "bar-label"), holder, node("span", String(count(row.n)), "bar-value"));
    out.push(line);
  });
  return out;
}

async function load() {
  try {
    const response = await fetch("/api/analisi", {cache: "no-store", signal: AbortSignal.timeout(6000)});
    if (!response.ok) throw new Error("analisi");
    const data = await response.json();
    $("status").textContent = "Ultimi " + count(data.giorni) + " giorni · conteggi anonimi, nessun testo né dato del cliente.";
    $("funnel").replaceChildren(...funnel(list(data.imbuto)));
    $("needs").replaceChildren(...bars(list(data.per_bisogno), "concetto", "eventi"));
    $("weeks").replaceChildren(...bars(list(data.complemento_per_settimana), "settimana", "mostrati", "accettati"));
    $("misses").replaceChildren(...bars(list(data.non_pertinenti), "concetto", "n"));
  } catch {
    $("status").textContent = "Analisi non disponibile: applicare la migrazione 006 e avviare il banco.";
  }
}

load();
