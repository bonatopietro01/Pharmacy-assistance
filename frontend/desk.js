const $ = id => document.getElementById(id);
const list = value => Array.isArray(value) ? value : [];
const euro = new Intl.NumberFormat("it-IT", {style: "currency", currency: "EUR"});
const activeMic = data => ["attivo", "avvio"].includes(data?.status?.microphone);
const knownErrors = new Set(["pagina", "stato", "microfono", "azione"]);
const reported = new Set();
const prices = cents => Number.isInteger(cents) ? euro.format(cents / 100) : null;

let snapshot = null;
let pollRequest = null;
let mutating = false;
let reachable = false;
let foreignSession = false;
let pageClosed = false;
let abandoned = null;
let pendingReset = null;
let selectedCode = null;
let selectedVariant = null;
let selectedVariantSource = null;
let previousResults = false;
let openedSources = null;
let voiceToken = null;
let voiceOptionsKey = "";
let selectedByVoice = false;
let correctionCandidates = new Map();
let settings = null;
let settingsBusy = false;
let inputDeviceNotice = "";
const resultPages = {products: 0, supplements: 0, offers: 0};

function node(tag, value = "", style) {
  const item = document.createElement(tag);
  item.textContent = value ?? "";
  if (style) item.className = style;
  return item;
}

async function request(route, body, keepalive = false) {
  const response = await fetch("/api/" + route, {
    method: "POST", cache: "no-store", keepalive,
    signal: keepalive ? undefined : AbortSignal.timeout(6000),
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
  });
  return {status: response.status, ok: response.ok, data: await response.json()};
}

function reportError(code) {
  if (knownErrors.has(code) && !reported.has(code)) {
    reported.add(code);
    request("errore-frontend/" + code, {}).catch(() => {});
  }
}

window.addEventListener("error", () => reportError("pagina"));

function isSnapshot(data) {
  return data?.schema_version === 1 && typeof data.session_id === "string"
    && Number.isInteger(data.version) && Number.isInteger(data.action_version);
}

function sourceLabel(source) {
  if (typeof source === "string") return source;
  if (!source) return "";
  return [source.label || source.id || source.kind, source.version && "v. " + source.version].filter(Boolean).join(" · ");
}

const renderKeys = new Map();
function refreshPart(id, data, build) {
  const key = JSON.stringify(data);
  if (renderKeys.get(id) === key) return;
  renderKeys.set(id, key);
  $(id).replaceChildren(...build());
}

function currentEvidence(data) {
  const transcript = data?.transcript;
  if (!transcript || typeof transcript.testo !== "string") return [];
  return list(data.evidence).filter(evidence => {
    const span = evidence.span;
    return ["active", "provisional"].includes(evidence.state)
      && span?.transcript_revision === transcript.revision && Number.isInteger(span.start) && Number.isInteger(span.end)
      && span.start >= 0 && span.end > span.start && span.end <= transcript.testo.length;
  });
}

function safeHttpsUrl(value) {
  if (typeof value !== "string" || value.length > 2048) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

function renderTranscript(transcript, evidence) {
  const text = transcript?.testo || "";
  const partial = transcript?.partial?.text || "";
  const finalSegments = list(transcript?.final_segments).map(segment => segment?.text || "").filter(Boolean);
  // The snapshot spans use offsets into this exact UTF-16 string.
  const partialStart = partial && text.endsWith(partial) ? text.length - partial.length : text.length;
  const boundaries = [0, text.length, partialStart];
  let cursor = 0;
  for (const segment of finalSegments) {
    const start = text.indexOf(segment, cursor);
    if (start < 0 || start + segment.length > partialStart) break;
    cursor = start + segment.length;
    boundaries.push(start, cursor);
  }
  for (const {span} of evidence) boundaries.push(span.start, span.end);
  const cuts = [...new Set(boundaries)].sort((a, b) => a - b);
  const scroller = $("transcript");
  const follow = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 36;
  const checkedSpans = list(snapshot?.checkpoint?.spans).filter(span => Number.isInteger(span?.start));
  refreshPart("transcript", [text, partialStart, cuts, evidence, checkedSpans], () => {
    return cuts.slice(1).map((end, index) => {
      const start = cuts[index];
      const found = evidence.filter(({span}) => span.start < end && span.end > start);
      const item = node(found.length ? "mark" : "span", text.slice(start, end));
      if (start >= partialStart) item.classList.add("partial");
      if (found.length) {
        item.classList.add("highlight");
        if (checkedSpans.some(span => span.start < end && span.end > start)) item.classList.add("checked");
        item.title = found.map(entry => entry.reason || sourceLabel(entry.source)).filter(Boolean).join(" · ");
      }
      return item;
    });
  });
  if (follow) scroller.scrollTop = scroller.scrollHeight;

}


function activeIngredientText(ingredient) {
  if (typeof ingredient === "string") return ingredient;
  if (typeof ingredient?.name !== "string") return "";
  return [ingredient.name, [ingredient.amount, ingredient.unit].filter(value => value != null).join(" ")]
    .filter(Boolean).join(" ");
}

function speciesLabel(display) {
  if (display?.category !== "medicinale_veterinario") return null;
  const scope = {cane: "cane", gatto: "gatto", cane_gatto: "cane e gatto"}[display.species_scope];
  return scope ? "Uso veterinario · " + scope : "Uso veterinario · specie da verificare";
}

function validProduct(item) {
  return typeof item?.code === "string" && item.code
    && typeof item.display?.name === "string" && item.display.name.trim()
    && (!item.display.code || item.display.code === item.code);
}

function variantsFor(row) {
  const variants = list(row.variants).filter(validProduct);
  const base = variants.find(item => item.code === row.code) || row;
  return [base, ...variants.filter(item => item.code !== row.code)];
}

function productFor(row, preferredCode = null) {
  const variants = variantsFor(row);
  const target = rowKey(row) === selectedCode && selectedVariant ? selectedVariant : preferredCode;
  return variants.find(item => item.code === target) || variants[0];
}

function compactFacts(display) {
  const ingredients = list(display.active_ingredients).map(activeIngredientText).filter(Boolean);
  return [...ingredients, display.strength, display.form_label || display.form, display.classification_label,
    speciesLabel(display)]
    .filter(Boolean).join(" · ");
}

function rowKey(row) {
  return JSON.stringify([row.section, row.code, row.offer?.codice || row.offer?.id || null]);
}

function offerDetails(offer) {
  if (!offer) return null;
  const cents = offer.prezzo_cent ?? offer.price_cents ?? offer.prezzo_promozionale_cent ?? offer.promotional_price_cents;
  const end = offer.data_fine || offer.fine || offer.end_date;
  const day = typeof end === "string" && /^\d{4}-\d{2}-\d{2}$/.test(end) ? end.split("-").reverse().join("/") : null;
  return {
    benefit: offer.beneficio || offer.benefit,
    price: Number.isInteger(cents) && cents >= 0 ? prices(cents) : null,
    validity: day ? "Fino al " + day : null,
    demo: offer.dimostrativa === true || offer.demo === true
  };
}

function cartItems(cart) {
  return list(cart?.items).filter(item => typeof item?.code === "string" && item.code);
}

function cartTotalText(cart, includePartial = true) {
  const cents = cart?.total_cents;
  if (!Number.isInteger(cents) || cents < 0) return "—";
  return prices(cents) + (includePartial && cart.partial === true ? " · parziale" : "");
}

function cartRowName(item) {
  return [item.name || item.display?.name, item.package_label].filter(Boolean).join(" · ") || item.code;
}

function appliedOfferDetails(offer) {
  if (!offer || typeof offer !== "object") return null;
  const cents = offer.price_cents ?? offer.prezzo_cent ?? offer.promotional_price_cents;
  const validityEnd = offer.end_date || offer.fine || offer.data_fine;
  return {
    code: offer.offer_code || offer.codice || offer.code,
    name: offer.title || offer.titolo || offer.name,
    benefit: offer.benefit || offer.beneficio,
    price_cents: Number.isInteger(cents) && cents >= 0 ? cents : null,
    price: Number.isInteger(cents) && cents >= 0 ? prices(cents) : null,
    demo: offer.demo === true || offer.dimostrativa === true,
    validity: typeof validityEnd === "string" ? validityEnd : null
  };
}

function renderCart(cart) {
  const items = cartItems(cart);
  const itemCount = Number.isInteger(cart?.item_count) && cart.item_count >= 0
    ? cart.item_count : items.reduce((sum, item) => sum + (Number.isInteger(item.quantity) ? item.quantity : 1), 0);
  $("open-cart").textContent = itemCount + (itemCount === 1 ? " pezzo · " : " pezzi · ") + cartTotalText(cart);

  const strip = items.map(item => [item.code, cartRowName(item)]);
  $("cart-strip").hidden = !items.length;
  refreshPart("cart-strip-items", [strip, mutating, snapshot?.checkpoint?.da_rivedere], () => items.map(item => {
    const line = node("li", "", "cart-strip-item");
    line.append(node("span", item.name || item.display?.name || item.code));
    const review = snapshot?.checkpoint?.da_rivedere?.[item.code];
    if (typeof review === "string") {
      const mark = node("span", "da rivedere", "label stop");
      mark.title = review;
      line.append(mark);
    }
    const remove = node("button", "Rimuovi");
    remove.type = "button";
    remove.setAttribute("aria-label", "Rimuovi " + (item.name || item.code) + " dal carrello");
    remove.disabled = mutating;
    remove.addEventListener("click", () => mutateSessionAction("rimuovi_carrello", {code: item.code}));
    line.append(remove);
    return line;
  }));

  const content = [];
  if (!items.length) {
    content.push(node("p", "Il carrello è vuoto.", "cart-empty"));
  } else {
    const rows = node("div", "", "cart-items");
    for (const item of items) {
      const line = node("article", "", "cart-item");
      const identity = node("div", "", "cart-item-name");
      identity.append(node("strong", item.name || item.display?.name || item.code));
      if (item.package_label) identity.append(node("span", item.package_label));
      if (item.demo === true || /demo|dimostrativ|fixture|synthetic/i.test(sourceLabel(item.price_source))) {
        identity.append(node("span", "Dati di prova", "badge cart-demo"));
      }
      const applied = appliedOfferDetails(item.applied_offer);
      if (applied) {
        const promoText = [applied.demo ? "Offerta di prova applicata" : "Offerta applicata",
          applied.name, applied.price, applied.benefit,
          applied.validity ? "Fino al " + applied.validity : null].filter(Boolean).join(" · ");
        identity.append(node("span", promoText));
      }
      const quantity = Number.isInteger(item.quantity) && item.quantity > 0 ? item.quantity : 1;
      const priceCents = Number.isInteger(applied?.price_cents)
        ? applied.price_cents : item.unit_price_cents;
      const unitPrice = Number.isInteger(priceCents) && priceCents >= 0 ? prices(priceCents) : "Prezzo non disponibile";
      const subtotal = Number.isInteger(item.subtotal_cents) && item.subtotal_cents >= 0
        ? prices(item.subtotal_cents) : "—";
      const savingsCents = Number.isInteger(item.unit_price_cents) && Number.isInteger(applied?.price_cents)
        && applied.price_cents <= item.unit_price_cents
        ? (item.unit_price_cents - applied.price_cents) * quantity : 0;
      line.append(identity,
        node("span", "Quantità " + quantity, "cart-meta cart-quantity"),
        node("span", "Unità " + unitPrice, "cart-meta cart-unit-price"),
        node("span", "Subtotale " + subtotal, "cart-meta"));
      if (savingsCents > 0) line.append(node("span", "Risparmio " + prices(savingsCents), "cart-meta"));
      const remove = node("button", "Rimuovi", "cart-remove");
      remove.type = "button";
      remove.setAttribute("aria-label", "Rimuovi " + (item.name || item.code) + " dal carrello");
      remove.disabled = mutating;
      remove.addEventListener("click", () => mutateSessionAction("rimuovi_carrello", {code: item.code}));
      line.append(remove);
      rows.append(line);
    }
    content.push(rows);
  }
  const total = node("div", "", "cart-summary");
  total.append(node("span", cart?.partial === true ? "Totale parziale" : "Totale"),
    node("strong", cartTotalText(cart, false)));
  if (Number.isInteger(cart?.savings_cents) && cart.savings_cents > 0) {
    total.append(node("span", "Risparmio totale " + prices(cart.savings_cents), "cart-meta"));
  }
  content.push(total);
  refreshPart("cart-content", [cart, mutating], () => content);
}

function documentedEquivalents(display) {
  return list(display.equivalents).filter(item => item?.name && item.source
    && ["approvata", "approved", "documented"].includes(item.review_status));
}

function sourcesKey(row, product) {
  return JSON.stringify([product.display, referenceDetails(row), row.covered_symptoms, row.uncovered_symptoms]);
}

function referenceLink(source) {
  const href = safeHttpsUrl(source?.url);
  if (!href) return null;
  const link = node("a", source.title || source.titolo || sourceLabel(source) || href);
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.referrerPolicy = "no-referrer";
  return link;
}

function referenceDetails(row) {
  return list(row.references).filter(item => item?.source).map(item => ({
    source: item.source, review_status: item.review_status, concept_name: item.concept_name, claim: item.claim,
    context: item.context, risks: item.risks, prerequisites: item.prerequisites, exclusions: item.exclusions
  }));
}

function showSources(row, product) {
  const contents = [node("h3", product.display.name)];
  const references = referenceDetails(row);
  const covered = list(row.covered_symptoms).filter(Boolean);
  const uncovered = list(row.uncovered_symptoms).filter(Boolean);
  if (covered.length || uncovered.length) {
    const block = node("div", "", "reference");
    if (covered.length) block.append(node("p", "Sintomi coperti · " + covered.join(", ")));
    if (uncovered.length) block.append(node("p", "Sintomi non coperti · " + uncovered.join(", ")));
    contents.push(block);
  }
  for (const reference of references) {
    const link = referenceLink(reference?.source);
    if (!link) continue;
    const block = node("div", "", "reference");
    if (reference.concept_name) block.append(node("strong", reference.concept_name));
    if (reference.claim) block.append(node("p", reference.claim));
    for (const value of [reference.context, reference.risks, reference.prerequisites, reference.exclusions]) {
      const text = Array.isArray(value) ? value.join(" · ") : value;
      if (typeof text === "string" && text.trim()) block.append(node("p", text));
    }
    block.append(link);
    contents.push(block);
  }
  const sourceLinks = list(product.display.sources).map(referenceLink).filter(Boolean);
  if (sourceLinks.length) {
    const block = node("ul", "", "reference");
    for (const link of sourceLinks) {
      const item = node("li");
      item.append(link);
      block.append(item);
    }
    contents.push(block);
  }
  const equivalents = documentedEquivalents(product.display);
  if (equivalents.length) {
    const block = node("div", "", "reference");
    block.append(node("strong", "Equivalenti documentati"));
    for (const item of equivalents) {
      const line = node("p", [item.name, item.conditions].filter(Boolean).join(" · "));
      const link = referenceLink(item.source);
      if (link) line.append(document.createTextNode(" · "), link);
      block.append(line);
    }
    contents.push(block);
  }
  $("sources-content").replaceChildren(...contents);
  openedSources = {row: rowKey(row), code: product.code, key: sourcesKey(row, product)};
  $("sources-dialog").showModal();
}

function closeSources() {
  openedSources = null;
  if ($("sources-dialog").open) $("sources-dialog").close();
  $("sources-content").replaceChildren();
}

function selectProduct(row, code, source = "row") {
  if (openedSources) closeSources();
  selectedCode = rowKey(row);
  selectedVariant = code;
  selectedVariantSource = source;
  selectedByVoice = false;
  renderResults(snapshot?.desk_results);
  const variants = variantsFor(row);
  if (typeof code === "string" && variants.some(item => item.code === code)
      && (variants.length === 1 || source !== "row")) {
    mutateSessionAction("seleziona_prodotto", {code});
  }
}

function rowLabels(row, product) {
  const box = node("span", "", "row-labels");
  const stock = product?.commercial?.stock ?? row?.commercial?.stock;
  if (Number.isInteger(stock)) {
    const dot = node("span", "", "stock-dot " + (stock <= 0 ? "out" : stock <= 3 ? "low" : "ok"));
    const label = node("span", stock <= 0 ? "esaurito" : stock <= 3 ? "giacenza bassa" : "disponibile", "label");
    label.prepend(dot);
    box.append(label);
  }
  const reviewed = list(row.references).some(item => item?.review_status === "approvata");
  if (list(row.references).length) box.append(node("span", reviewed ? "approvata" : "non revisionata", reviewed ? "label" : "label warn"));
  for (const text of list(row.labels)) {
    if (typeof text !== "string") continue;
    box.append(node("span", text, text === "richiede ricetta" ? "label stop" : "label warn"));
  }
  if (typeof row.not_proposable === "string") box.append(node("span", "non proponibile", "label stop"));
  return box;
}

const expandedRows = new Set();

function coverageLabel(row) {
  const covered = list(row.covered_symptoms).length;
  const total = covered + list(row.uncovered_symptoms).length;
  return total > 1 ? "copre " + covered + " su " + total : null;
}

function iconButton(symbol, label, style) {
  const button = node("button", symbol, "icon-button " + style);
  button.type = "button";
  button.setAttribute("aria-label", label);
  button.title = label;
  return button;
}

function thumbnail(display) {
  const image = typeof display?.image === "string" && display.image.startsWith("/farmaco/immagini/") ? display.image : null;
  if (image) {
    const img = node("img", "", "thumb");
    img.src = image;
    img.alt = "";
    img.width = img.height = 40;
    return img;
  }
  const category = String(display?.category || display?.classification_label || "").toLowerCase();
  return node("span", category.includes("integrator") ? "🌿" : category.includes("dispositiv") ? "🩹" : "💊", "thumb thumb-icon");
}

function cardLabels(row, product) {
  // At most three labels on the card: stock, coverage, then the most important caution.
  const box = node("span", "", "row-labels");
  const stock = product?.commercial?.stock ?? row?.commercial?.stock;
  if (Number.isInteger(stock)) {
    const label = node("span", stock <= 0 ? "esaurito" : stock <= 3 ? "giacenza " + stock : "disponibile", "label");
    label.prepend(node("span", "", "stock-dot " + (stock <= 0 ? "out" : stock <= 3 ? "low" : "ok")));
    box.append(label);
  }
  const coverage = coverageLabel(row);
  if (coverage) box.append(node("span", coverage, "label"));
  const cautions = [];
  if (typeof row.not_proposable === "string") cautions.push(["non proponibile", "label stop"]);
  for (const text of list(row.labels)) {
    if (typeof text === "string") cautions.push([text, text === "richiede ricetta" ? "label stop" : "label warn"]);
  }
  if (list(row.references).length) {
    const reviewed = list(row.references).some(item => item?.review_status === "approvata");
    cautions.push(reviewed ? ["approvata", "label"] : ["non revisionata", "label warn"]);
  }
  const slots = Math.max(0, 3 - box.childElementCount);
  for (const [text, style] of cautions.slice(0, slots)) box.append(node("span", text, style));
  return {box, hidden: cautions.slice(slots)};
}

function resultRow(row, selected, option, preference, preferredCode = null, index = 0) {
  const product = selected ? productFor(row, preferredCode) : row;
  const key = rowKey(row);
  const article = node("article", "", "result-row card");
  article.classList.toggle("selected", selected);
  if (option || preference) article.classList.add("voice-match");
  const offer = offerDetails(row.offer);
  const select = node("button", "", "result-select");
  select.type = "button";
  select.setAttribute("aria-pressed", String(selected));
  select.dataset.row = key;
  const first = node("span", "", "card-line");
  const name = [product.display.name, product.display.form_label || product.display.form].filter(Boolean).join(" · ");
  const title = node("strong", name, "card-name truncate");
  title.title = [name, compactFacts(product.display)].filter(Boolean).join(" · ");
  first.append(title);
  const cents = offer?.price_cents ?? product.commercial?.bank_price_cents ?? row.commercial?.bank_price_cents;
  first.append(node("span", offer ? (offer.price || offer.benefit || "Offerta") : prices(cents) || "—", "card-price"));
  const second = node("span", "", "card-line");
  const {box, hidden} = cardLabels(row, product);
  const review = snapshot?.checkpoint?.da_rivedere?.[row.code] || snapshot?.checkpoint?.da_rivedere?.[product.code];
  if (typeof review === "string") {
    const mark = node("span", "da rivedere", "label stop");
    mark.title = review;
    box.prepend(mark);
    if (box.childElementCount > 3) box.lastChild.remove();
  }
  if (offer) box.prepend(node("span", offer.demo ? "offerta di prova" : "in offerta", "label"));
  if (option) box.prepend(node("span", "possibile scelta", "label voice-marker"));
  else if (preference) box.prepend(node("span", "forma richiesta", "label voice-marker"));
  second.append(box);
  const body = node("span", "", "card-body");
  body.append(first, second);
  if (row.section === "products") select.append(node("span", String(index + 1), "rank-number"));
  select.append(thumbnail(product.display), body);
  select.addEventListener("click", () => {
    if (selected && selectedCode === key && !selectedByVoice) {
      resetSelection();
      renderResults(snapshot?.desk_results);
    } else {
      selectProduct(row, product.code, selected && selectedByVoice ? "voice" : "row");
    }
    [...document.querySelectorAll(".result-select")].find(button => button.dataset.row === key)?.focus();
  });
  article.append(select);

  const actions = node("div", "", "card-actions");
  const variants = variantsFor(row);
  const ambiguousVoice = list(snapshot?.desk_results?.voice_options).length > 1;
  const explicitlySelected = selected && key === selectedCode && variants.some(item => item.code === selectedVariant)
    && (["voice", "variant", "preferred"].includes(selectedVariantSource)
      || selectedVariantSource === "row" && variants.length === 1);
  const canAdd = !ambiguousVoice && variants.length === 1 || explicitlySelected;
  const addCode = variants.length === 1 ? variants[0].code : canAdd ? selectedVariant : null;
  if (row.section === "products") {
    const confirmCode = addCode;
    const confirmed = snapshot?.product?.confirmed_code === confirmCode && confirmCode;
    const confirm = iconButton("✓", confirmed ? product.display.name + " confermato"
      : "Conferma " + product.display.name + " come prodotto scelto", "confirm-row");
    confirm.classList.toggle("done", Boolean(confirmed));
    confirm.disabled = mutating || !confirmCode || Boolean(confirmed) || typeof row.not_proposable === "string"
      || snapshot?.vendita?.proposals_blocked === true;
    confirm.dataset.confirmCode = confirmCode || "";
    confirm.addEventListener("click", () => confirmCode && mutateSessionAction("conferma_prodotto", {code: confirmCode}));
    actions.append(confirm);
  }
  const add = iconButton("+", canAdd
    ? "Aggiungi " + (variants.find(item => item.code === addCode)?.display?.name || product.display.name) + " al carrello"
    : "Scegli una confezione prima di aggiungerla al carrello", "cart-add");
  add.disabled = !canAdd || mutating;
  add.addEventListener("click", () => { if (addCode) mutateSessionAction("aggiungi_carrello", {code: addCode}); });
  actions.append(add);
  const hasSources = list(row.references).some(item => safeHttpsUrl(item?.source?.url))
    || list(product.display.sources).some(item => safeHttpsUrl(item?.url))
    || list(row.covered_symptoms).length || list(row.uncovered_symptoms).length
    || documentedEquivalents(product.display).length;
  const info = iconButton("i", "Fonti e dettagli di " + product.display.name, "sources-button");
  info.disabled = !hasSources;
  info.addEventListener("click", () => showSources(row, product));
  actions.append(info);
  const expanded = expandedRows.has(key);
  const more = iconButton(expanded ? "▴" : "▾", (expanded ? "Chiudi" : "Apri") + " i dettagli di " + product.display.name,
    "expand-row");
  more.setAttribute("aria-expanded", String(expanded));
  more.addEventListener("click", () => {
    if (expandedRows.has(key)) expandedRows.delete(key); else expandedRows.add(key);
    renderResults(snapshot?.desk_results);
    [...document.querySelectorAll(".expand-row")].find(button => button.closest(".card")?.querySelector(".result-select")?.dataset.row === key)?.focus();
  });
  actions.append(more);
  article.append(actions);

  const isCheckout = snapshot?.desk_phase?.key === "closing" || snapshot?.desk_results?.phase === "closing";
  const offerCode = row.offer?.codice || row.offer?.offer_code || row.offer?.code;
  const inCart = cartItems(snapshot?.cart).some(item => item.code === product.code);
  const details = node("div", "", "card-details");
  details.hidden = !expanded && !(variants.length > 1 && selected && !explicitlySelected);
  if (typeof row.rank_reason === "string" && row.rank_reason) details.append(node("p", "Perché è qui: " + row.rank_reason, "rank-reason"));
  const facts = offer ? [offer.benefit, offer.validity ? "fino al " + offer.validity : null]
    : [compactFacts(product.display), list(row.symptoms).filter(Boolean).join(", ")];
  const factText = facts.filter(Boolean).join(" · ");
  if (factText) details.append(node("p", factText, "result-facts"));
  if (hidden.length) {
    const cautionBox = node("p", "", "row-labels");
    for (const [text, style] of hidden) cautionBox.append(node("span", text, style));
    details.append(cautionBox);
  }
  if (typeof row.not_proposable === "string") details.append(node("p", row.not_proposable, "rank-reason"));
  if (variants.length > 1) {
    const options = node("select", "", "variants");
    options.setAttribute("aria-label", "Confezione di " + row.display.name);
    options.dataset.row = key;
    options.append(node("option", "Scegli confezione"));
    options.lastChild.value = "";
    options.lastChild.disabled = true;
    for (const variant of variants) {
      const choice = node("option", variant.label || variant.display.package_label || variant.display.name);
      choice.value = variant.code;
      options.append(choice);
    }
    options.value = selected && selectedVariantSource !== "row" ? selectedVariant || "" : "";
    options.addEventListener("change", () => {
      selectProduct(row, options.value, "variant");
      [...document.querySelectorAll(".variants")].find(menu => menu.dataset.row === key)?.focus();
    });
    details.append(options);
  }
  const detailActions = node("div", "", "actions");
  if (row.section === "products" && list(row.references).length) {
    const reject = node("button", "Non pertinente", "not-relevant small-button");
    reject.type = "button";
    reject.disabled = mutating;
    reject.dataset.rejectCode = product.code;
    reject.addEventListener("click", () => mutateSessionAction("feedback", {evento: "non_pertinente", code: product.code}));
    detailActions.append(reject);
  }
  if (row.section === "offers" && offer && isCheckout && inCart && typeof offerCode === "string" && offerCode) {
    const applyOffer = node("button", "Applica offerta", "apply-offer small-button");
    applyOffer.type = "button";
    applyOffer.disabled = mutating;
    applyOffer.setAttribute("aria-label", "Applica l’offerta a " + product.display.name);
    applyOffer.addEventListener("click", () => mutateSessionAction("applica_offerta", {
      code: product.code, offer_code: offerCode
    }));
    if (row.section === "offers") { details.hidden = false; }
    detailActions.append(applyOffer);
  }
  if (detailActions.childElementCount) details.append(detailActions);
  if (details.childElementCount) article.append(details);
  return article;
}

function renderSales(product, waiting, promo) {
  const commercial = product?.commercial || {};
  const offer = offerDetails(promo);
  refreshPart("product-sales", [
    product?.code, product?.display, product?.label, offer,
    commercial.bank_price_cents, commercial.bank_price_source, commercial.stock, commercial.stock_source, waiting
  ], () => {
    if (!product) return waiting ? [node("p", "Seleziona un prodotto.", "result-state")] : [];
    const priceSource = sourceLabel(commercial.bank_price_source);
    const stockSource = sourceLabel(commercial.stock_source);
    const demo = source => product.display.dataset_type === "demo"
      || /demo|dimostrativ|fixture|synthetic/i.test([source?.kind, sourceLabel(source)].filter(Boolean).join(" "));
    const price = priceSource && commercial.bank_price_cents >= 0 ? prices(commercial.bank_price_cents) : null;
    const stock = stockSource && Number.isInteger(commercial.stock) && commercial.stock >= 0
      ? (commercial.stock === 0 ? "Esaurito" : commercial.stock + " unità") : null;
    const format = [product.label, product.display.strength, product.display.form_label || product.display.form,
      product.display.classification_label, speciesLabel(product.display)].filter(Boolean).join(" · ");
    const blocks = [
      node("h3", product.display.name, "sale-name"),
      ...(format ? [node("p", format, "result-state")] : []),
    ];
    if ((price && demo(commercial.bank_price_source)) || (stock && demo(commercial.stock_source))) {
      blocks.push(node("p", "Dati di prova", "badge"));
    }
    if (offer) {
      const block = node("div", "", "sale-value");
      block.append(node("span", offer.demo ? "Offerta di prova" : "Offerta della farmacia", "result-state"));
      if (offer.benefit) block.append(node("span", offer.benefit));
      if (offer.price) block.append(node("strong", offer.price));
      if (offer.validity) block.append(node("span", offer.validity, "result-state"));
      blocks.push(block);
    }
    for (const [label, value, source] of [
      [demo(commercial.bank_price_source) ? "Prezzo di prova" : "Prezzo al banco", price, priceSource],
      [demo(commercial.stock_source) ? "Disponibilità di prova" : "Disponibilità", stock, stockSource]
    ]) {
      const block = node("div", "", "sale-value");
      block.append(node("span", label, "result-state"));
      block.append(node("strong", value || "Dato non disponibile"));
      if (value && source) block.title = source;
      blocks.push(block);
    }
    return blocks;
  });
}

function renderPage(id, rows, limit, selected, voiceOptions, preferences, preferredCode) {
  const total = Math.max(1, Math.ceil(rows.length / limit));
  const page = Math.min(resultPages[id], total - 1);
  resultPages[id] = page;
  const visible = rows.slice(page * limit, (page + 1) * limit);
  // Commercial timestamps can change at each poll. Keep focused controls stable.
  const flags = visible.map(row => {
    const codes = variantsFor(row).map(item => item.code);
    return [codes.some(code => voiceOptions.includes(code)), codes.some(code => preferences.includes(code))];
  });
  const key = visible.map(row => [rowKey(row), row.display, row.relevance, row.affinity_percent, row.symptoms,
    row.covered_symptoms, row.uncovered_symptoms, referenceDetails(row), row.offer,
    list(row.variants).map(item => [item.code, item.display, item.label]),
    row.labels, row.rank_reason, row.not_proposable, row.commercial?.stock]);
  refreshPart(id, [key, selected && rowKey(selected), selectedVariant, selectedVariantSource,
    selectedByVoice, preferredCode, flags, mutating, snapshot?.product?.confirmed_code,
    snapshot?.vendita?.proposals_blocked, [...expandedRows], cartItems(snapshot?.cart).map(item => item.code),
    snapshot?.checkpoint?.da_rivedere,
    snapshot?.desk_phase?.key],
    () => visible.map((row, index) => resultRow(row, row === selected, ...flags[index], preferredCode,
      page * limit + index)));
  $(id + "-pages").hidden = total < 2;
  refreshPart(id + "-pages", [page, total], () => {
    if (total < 2) return [];
    const arrow = (offset, label) => {
      const button = node("button", label);
      button.type = "button";
      button.disabled = page + offset < 0 || page + offset >= total;
      button.addEventListener("click", () => {
        resultPages[id] = page + offset;
        renderResults(snapshot?.desk_results);
        const buttons = [...$(id + "-pages").querySelectorAll("button:not(:disabled)")];
        (offset < 0 ? buttons[0] : buttons.at(-1))?.focus();
      });
      return button;
    };
    return [arrow(-1, "Indietro"), node("span", (page + 1) + " / " + total), arrow(1, "Avanti")];
  });
}

function resetSelection() {
  selectedCode = selectedVariant = null;
  selectedVariantSource = null;
  selectedByVoice = false;
}

function resetResultState() {
  resetSelection();
  voiceToken = null;
  voiceOptionsKey = "";
  previousResults = false;
  for (const section of Object.keys(resultPages)) resultPages[section] = 0;
  correctionCandidates.clear();
  if ($("correction-dialog").open) $("correction-dialog").close();
}

function syncVoiceSelection(results, rows, sections, limits, options) {
  const choice = results?.voice_choice;
  const optionsKey = JSON.stringify([...new Set(options)].sort());
  if (!choice && options.length && optionsKey !== voiceOptionsKey) resetSelection();
  voiceOptionsKey = optionsKey;
  if (!choice) {
    if (selectedByVoice) resetSelection();
    return;
  }
  if (typeof choice.token !== "string" || !choice.token || choice.token === voiceToken) return;
  const section = choice.section === "rows" ? "products" : choice.section;
  const row = rows.find(item => (!section || item.section === section)
    && (!choice.row_code || item.code === choice.row_code)
    && (!choice.offer_code || (item.offer?.codice || item.offer?.id) === choice.offer_code)
    && variantsFor(item).some(variant => variant.code === choice.code));
  if (!row) return;
  if (openedSources) closeSources();
  voiceToken = choice.token;
  selectedByVoice = true;
  selectedCode = rowKey(row);
  selectedVariant = choice.code;
  selectedVariantSource = "voice";
  resultPages[row.section] = Math.floor(sections[row.section].indexOf(row) / limits[row.section]);
}

function renderResults(results) {
  const fromSection = (section, value) => list(value).filter(validProduct).map(row => ({...row, section}));
  const products = fromSection("products", results?.rows);
  const supplements = fromSection("supplements", results?.supplements);
  const offers = fromSection("offers", results?.phase && results.phase !== "offer" ? [] : results?.offers)
    .filter(row => row.offer && typeof row.offer === "object");
  const sections = {products, supplements, offers};
  const visibleRows = products.concat(supplements, offers);
  const visibleCodes = new Set(visibleRows.flatMap(row => variantsFor(row).map(item => item.code)));
  const corrections = fromSection("corrections", results?.correction_options)
    .filter(row => !visibleCodes.has(row.code));
  const rows = visibleRows.concat(corrections);
  const previous = results?.previous === true;
  const retained = rows.find(row => rowKey(row) === selectedCode);
  if ((previousResults && !previous) || !retained
      || !variantsFor(retained).some(item => item.code === selectedVariant)) resetSelection();
  if (previousResults && !previous || !rows.length) {
    for (const section of Object.keys(resultPages)) resultPages[section] = 0;
  }
  previousResults = previous;
  const voiceOptions = list(results?.voice_options).filter(code => typeof code === "string");
  const preferences = list(results?.preference_codes).filter(code => typeof code === "string");
  const compact = window.innerHeight < 660 || window.innerWidth < 790;
  const limits = {
    products: 8,
    supplements: compact ? 1 : 2,
    offers: 2
  };
  syncVoiceSelection(results, visibleRows, sections, limits, voiceOptions);
  const manual = rows.find(row => rowKey(row) === selectedCode);
  const preferred = !voiceOptions.length && !preferences.length
    ? products.find(row => row.code === results?.preferred_code) : null;
  const selected = manual || preferred;
  if (!manual && preferred && !selectedByVoice) {
    selectedCode = rowKey(preferred);
    selectedVariant = results.preferred_code;
    selectedVariantSource = "preferred";
  }
  const selectedProduct = selected ? productFor(selected, results?.preferred_code) : null;
  if (openedSources) {
    const row = rows.find(item => rowKey(item) === openedSources.row);
    const product = row && variantsFor(row).find(item => item.code === openedSources.code);
    if (!product || openedSources.key !== sourcesKey(row, product)) closeSources();
  }
  const resultState = [previous && rows.length ? "Risultati precedenti" : "",
    voiceOptions.length ? "Scelta vocale ambigua" : ""].filter(Boolean).join(" · ");
  $("result-state").textContent = resultState;
  $("review-label").hidden = !rows.some(row => list(row.references).some(item => item?.review_status === "candidata"));
  const followup = results?.supplement_followup;
  $("supplement-section").hidden = !supplements.length && followup?.active !== true;
  $("supplement-status").hidden = supplements.length > 0 || followup?.active !== true;
  $("supplement-status").textContent = followup?.active === true && !supplements.length
    ? "Nessun abbinamento documentato disponibile per il prodotto scelto." : "";
  $("offer-section").hidden = !offers.length;
  document.querySelector(".sales-panel").classList.toggle("has-offers", offers.length > 0);
  $("recognized-name").textContent = selectedProduct
    && results?.manual_corrected_code === selectedProduct.code
    ? "Nome corretto · " + selectedProduct.display.name
    : results?.recognized_name ? "Nome riconosciuto · " + results.recognized_name : "";
  for (const [section, sectionRows] of Object.entries(sections)) {
    renderPage(section, sectionRows, limits[section], selected, voiceOptions, preferences, results?.preferred_code);
  }
  const pinned = snapshot?.product?.current_code && validProduct({
    code: snapshot.product.current_code, display: snapshot.product.display
  }) ? {code: snapshot.product.current_code, display: snapshot.product.display,
    commercial: snapshot.product.commercial || {}} : null;
  const pinnedCartItem = cartItems(snapshot?.cart).find(item => item.code === pinned?.code);
  renderSales(pinned, visibleRows.length > 0, pinnedCartItem?.applied_offer);
  renderCart(snapshot?.cart || {items: [], item_count: 0, total_cents: 0, partial: false});
  renderLinked(results, selected?.section === "products" ? selected.code : null, products.length);
  renderWithProduct(results?.with_product);
  updateCorrections(previous ? [] : rows, voiceOptions);
}

function updateCorrections(rows, voiceOptions) {
  const items = new Map();
  for (const row of rows) {
    for (const product of variantsFor(row)) {
      const prior = items.get(product.code);
      if (!prior || (row.section === "products" && prior.row.section !== "products")) {
        items.set(product.code, {row, product});
      }
    }
  }
  correctionCandidates = items;
  $("correct-name").disabled = !items.size;
  if (!$("correction-dialog").open) return;
  if (!items.size) return $("correction-dialog").close();
  const ordered = [...items.values()].sort((a, b) => Number(voiceOptions.includes(b.product.code))
    - Number(voiceOptions.includes(a.product.code)));
  const label = ({row, product}) => [product.display.name, product.label || product.display.package_label,
    product.display.strength, product.display.form_label || product.display.form,
    voiceOptions.includes(product.code) || row.section === "corrections" ? "Possibile nome" : null,
    row.section === "offers" ? "In offerta" : null].filter(Boolean).join(" · ");
  refreshPart("correction-options", ordered.map(item => [item.product.code, label(item)]), () => ordered.map(item => {
    const button = node("button", label(item));
    button.type = "button";
    button.addEventListener("click", () => {
      const live = correctionCandidates.get(item.product.code);
      if (!live) return;
      $("correction-dialog").close();
      correctName(live.product.code);
    });
    return button;
  }));
}

async function correctName(code) {
  if (mutating || pageClosed || !activeMic(snapshot)) return;
  mutating = true;
  updateControls();
  $("message").textContent = "";
  try {
    await pollRequest;
    if (pageClosed || !activeMic(snapshot)) return;
    const body = actionBody(snapshot, "correggi_nome");
    body.payload = {code};
    const response = await request("azione", body);
    if (pageClosed) return;
    if (response.status === 409 && isSnapshot(response.data)) inspectStatus(response.data);
    if (!response.ok || !isSnapshot(response.data)) {
      $("message").textContent = "Il nome non è più disponibile per la correzione.";
      return;
    }
    resetSelection();
    applySnapshot(response.data);
  } catch {
    if (!pageClosed) $("message").textContent = "Correzione non applicata. Riprova.";
  } finally {
    mutating = false;
    updateControls();
  }
}

function renderPhase(phase, evidence, transcript, recipient) {
  const title = phase?.label ? "Trascrizione · " + phase.label : "Trascrizione";
  $("transcript-title").textContent = title;
  const item = evidence.find(entry => entry.id === phase?.evidence_id);
  const term = item?.matched_term || (item && transcript?.testo?.slice(item.span.start, item.span.end).trim());
  const source = {openai: "OpenAI", local: "Agente locale", manual: "Farmacista"}[phase?.source] || "";
  const hint = typeof term === "string" && term ? "Indizio: " + term.slice(0, 70) : "";
  const fields = ["dichiarato", "manuale"].includes(recipient?.source) ? recipient.declared_fields : null;
  const age = Number.isInteger(fields?.age) ? fields.age + " anni" : "";
  const person = [fields?.gender, recipient?.source === "dichiarato" ? recipient.relation : null, age]
    .filter(Boolean).join(", ");
  const recipientHint = person ? "Destinatario: " + person + (age ? " · Verifica età nelle fonti" : " · Chiarisci l’età se rilevante") : "";
  const reason = [phase?.reason, hint, source, recipientHint].filter(Boolean).join(" · ");
  const indicator = $("phase-reason");
  if (indicator.textContent !== reason) {
    indicator.textContent = reason;
    indicator.title = reason;
  }
}
function render(data) {
  const recording = activeMic(data);
  const status = !reachable ? "Banco non raggiungibile"
    : foreignSession ? "Ascolto attivo in un’altra sessione"
    : pendingReset ? "Sessione precedente da azzerare"
    : ({spento: "Microfono spento", avvio: "Avvio microfono…", attivo: "In ascolto", errore: "Microfono non disponibile"})[data?.status?.microphone] || "Microfono spento";
  if ($("status").textContent !== status) $("status").textContent = status;
  $("status").classList.toggle("recording", recording);
  $("listen").textContent = recording ? "Termina" : "Inizia ascolto";

  const live = recording ? data : null;
  const evidence = currentEvidence(live);
  renderPhase(live?.desk_phase, evidence, live?.transcript, live?.recipient);
  renderTranscript(live?.transcript, evidence);
  renderResults(live?.desk_results);
  renderVendita(live?.vendita, live?.desk_results);
  renderRecipient(live?.recipient_profile);
  renderCheckpoint(live?.checkpoint);
  updateControls();
}

function linkFor(item, code) {
  return list(item?.linked_to).find(link => link?.code_farmaco === code) || null;
}

const levelNames = {1: "Abbinamento approvato", 2: "Approvato per il bisogno", 3: "Stesso bisogno · non revisionato"};

function symptomNames(item) {
  return list(item?.for_symptoms).map(entry => entry?.nome).filter(Boolean);
}

function linkedCard(item, mode, link) {
  const card = node("article", "", "linked-card");
  card.classList.toggle("focus", mode === "focus");
  card.classList.toggle("dimmed", mode === "dimmed");
  const head = node("div", "", "card-line");
  head.append(thumbnail({category: item.kind}), node("strong", item.name || item.code, "card-name truncate"),
    node("span", prices(item.price_cents) || "—", "card-price"));
  const add = iconButton("+", "Aggiungi " + (item.name || item.code) + " al carrello", "cart-add");
  add.disabled = mutating || !activeMic(snapshot);
  add.addEventListener("click", () => mutateSessionAction("aggiungi_carrello", {code: item.code}));
  head.append(add);
  card.append(head);
  const labels = node("span", "", "row-labels");
  const symptom = mode === "symptom" ? list(item.for_symptoms)[0] : null;
  const level = link ? link.livello : symptom ? symptom.livello : item.level;
  if (symptom) labels.append(node("span", "per: " + symptomNames(item).join(", "), "label symptom"));
  labels.append(node("span", level >= 3 ? "non revisionato" : levelNames[level] || item.level_label,
    level >= 3 ? "label warn level" : "label level"));
  if (Number.isInteger(item.stock)) {
    const stock = node("span", item.stock <= 3 ? "giacenza " + item.stock : "disponibile", "label");
    stock.prepend(node("span", "", "stock-dot " + (item.stock <= 3 ? "low" : "ok")));
    labels.append(stock);
  }
  if (!symptom && list(item.linked_to).length > 1) labels.append(node("span", "per " + list(item.linked_to).length + " farmaci", "label"));
  card.append(labels);
  const reason = (link || symptom || list(item.linked_to)[0] || list(item.for_symptoms)[0])?.motivo;
  if (reason) {
    const text = node("span", reason, "rank-reason truncate");
    text.title = reason;
    card.append(text);
  }
  return card;
}

function renderLinked(results, selectedDrug, drugCount) {
  const confirmed = snapshot?.product?.confirmed_code || null;
  const focus = selectedDrug || confirmed;
  const complementCode = snapshot?.vendita?.complement?.code;
  const items = list(results?.linked_supplements).filter(item => typeof item?.code === "string")
    .filter(item => !(confirmed && complementCode === item.code));
  // Group 1: for the chosen drug (highlighted) · other drugs on the list (dimmed when a drug is chosen)
  // Group 2: for the symptoms said — always visible, never dimmed: they are useful anyway.
  const forDrug = [], otherDrugs = [], forSymptoms = [];
  for (const item of items) {
    const link = focus ? linkFor(item, focus) : null;
    if (link) forDrug.push([item, link]);
    else if (list(item.linked_to).length && (!focus || !list(item.for_symptoms).length)) otherDrugs.push(item);
    else if (list(item.for_symptoms).length) forSymptoms.push(item);
  }
  forDrug.sort((a, b) => a[1].livello - b[1].livello);
  const complementShown = Boolean(confirmed && complementCode);
  const emptyBox = snapshot?.vendita?.complement_empty === true;
  $("linked-state").textContent = (!drugCount && !items.length) || (complementShown && !items.length) || emptyBox ? ""
    : !items.length ? "Nessun integratore documentato per i farmaci in lista o per i sintomi detti."
    : !focus && otherDrugs.length ? "Tocca un farmaco (o 1–3) per evidenziare i suoi integratori." : "";
  refreshPart("linked", [items, focus, mutating, activeMic(snapshot)], () => {
    const out = [];
    if (!items.length) return out;
    if (focus && (forDrug.length || !complementShown)) {
      out.push(node("h3", "Per il farmaco scelto", "linked-group"));
      if (forDrug.length) out.push(...forDrug.map(([item, link]) => linkedCard(item, "focus", link)));
      else out.push(node("p", "Nessun abbinamento documentato per il farmaco scelto.", "result-state"));
    }
    if (otherDrugs.length) {
      if (!focus) out.push(node("h3", "Per i farmaci in lista", "linked-group"));
      out.push(...otherDrugs.map(item => linkedCard(item, focus ? "dimmed" : "plain", null)));
    }
    if (forSymptoms.length) {
      out.push(node("h3", "Per i sintomi detti", "linked-group"));
      out.push(...forSymptoms.map(item => linkedCard(item, "symptom", null)));
    }
    return out;
  });
}

function renderRecipient(profile) {
  const text = typeof profile?.label === "string" && profile.label ? profile.label : null;
  const chip = $("recipient-chip");
  chip.textContent = "Per: " + (text || "non indicato");
  chip.classList.toggle("unsure", Boolean(text && text.includes("da confermare")));
  chip.classList.toggle("known", Boolean(text && !text.includes("da confermare")));
  chip.disabled = !activeMic(snapshot) || mutating;
  if (chip.disabled) $("recipient-panel").hidden = true;
}

function renderWithProduct(info) {
  const box = $("with-product");
  const items = [];
  if (info?.supplement) items.push(["supplement", info.supplement]);
  for (const offer of list(info?.offers)) items.push(["offer", offer]);
  box.hidden = !info?.code;
  refreshPart("with-product-items", [info, mutating], () => {
    if (!info?.code) return [];
    const out = items.map(([kind, item]) => {
      const card = node("article", "", "linked-card focus compact");
      const head = node("div", "", "card-line");
      const title = kind === "offer" ? (item.title || "Offerta") + (item.name ? " · " + item.name : "") : item.name;
      head.append(node("strong", title, "card-name truncate"),
        node("span", prices(item.price_cents) || "—", "card-price"));
      const add = iconButton("+", "Aggiungi " + (item.name || item.code) + " al carrello", "cart-add");
      add.disabled = mutating || !activeMic(snapshot);
      add.addEventListener("click", () => mutateSessionAction("aggiungi_carrello", {code: item.code}));
      head.append(add);
      card.append(head);
      const labels = node("span", "", "row-labels");
      if (kind === "offer") {
        labels.append(node("span", item.demo ? "offerta di prova" : "offerta", "label"));
        labels.append(node("span", item.reason, "label"));
        if (item.end) labels.append(node("span", "fino al " + item.end, "label"));
      } else {
        if (item.origin === "sintomo" && symptomNames(item).length) {
          labels.append(node("span", "per: " + symptomNames(item).join(", "), "label symptom"));
        }
        labels.append(node("span", item.level >= 3 ? "non revisionato" : levelNames[item.level] || item.level_label,
          item.level >= 3 ? "label warn" : "label level"));
      }
      card.append(labels);
      const reason = kind === "offer" ? item.benefit : (list(item.linked_to)[0] || list(item.for_symptoms)[0])?.motivo;
      if (reason) card.append(node("span", reason, "rank-reason truncate"));
      return card;
    });
    if (info.offers_empty) {
      const line = node("p", "Nessuna offerta attiva su questo prodotto · ", "result-state");
      const link = node("a", "Crea offerta");
      link.href = "/farmaco#" + encodeURIComponent(info.code) + "&offerta";
      link.target = "_blank";
      link.rel = "noopener";
      line.append(link);
      out.push(line);
    }
    return out;
  });
}

const correctionNames = {manca_sintomo: "Sintomo non coperto", prodotto_non_coerente: "Farmaco da rivedere",
  integratore_non_adatto: "Integratore da rivedere", ordine: "Ordine"};
const agentNames = {in_corso: "agente al lavoro", ok: "agente ok", timeout: "agente: tempo scaduto",
  scartato: "agente: risposta scartata", provider_non_disponibile: "agente non disponibile"};

function renderCheckpoint(checkpoint) {
  const row = $("check-row");
  row.hidden = !checkpoint?.n;
  if (!checkpoint?.n) { $("check-panel").hidden = true; return; }
  const open = list(checkpoint.correzioni).filter(item => !item?.automatica);
  const auto = list(checkpoint.correzioni).filter(item => item?.automatica);
  const review = Object.keys(checkpoint.da_rivedere || {}).length;
  const count = open.length + (open.length ? 0 : review);
  const label = "Controllo dopo " + checkpoint.n + (checkpoint.n === 1 ? " parola chiave · " : " parole chiave · ")
    + (count ? count + (count === 1 ? " suggerimento" : " suggerimenti") : "ok")
    + (agentNames[checkpoint.agente] ? " · " + agentNames[checkpoint.agente] : "");
  const toggle = $("check-toggle");
  toggle.textContent = label;
  toggle.classList.toggle("warn", count > 0);
  toggle.title = list(checkpoint.parole).length ? "Ultime parole controllate: " + checkpoint.parole.join(", ") : "";
  refreshPart("check-panel", [checkpoint, mutating], () => {
    const out = [];
    for (const item of open) {
      const line = node("div", "", "check-item");
      line.append(node("strong", correctionNames[item.tipo] || item.tipo), node("span", " · " + (item.motivo || ""),
        "result-facts"));
      if (item.da === "modello") line.append(node("span", "modello", "label"));
      const actions = node("span", "", "check-actions");
      if (item.applicabile) {
        const apply = node("button", item.azione === "togli dal carrello" ? "Togli dal carrello" : "Applica", "small-button primary");
        apply.type = "button";
        apply.disabled = mutating || !activeMic(snapshot);
        apply.addEventListener("click", () => mutateSessionAction("controllo", {id: item.id, decisione: "applica"}));
        actions.append(apply);
      }
      const ignore = node("button", "Ignora", "small-button");
      ignore.type = "button";
      ignore.disabled = mutating || !activeMic(snapshot);
      ignore.addEventListener("click", () => mutateSessionAction("controllo", {id: item.id, decisione: "ignora"}));
      actions.append(ignore);
      line.append(actions);
      out.push(line);
    }
    for (const item of auto) out.push(node("p", "Fatto: " + (item.motivo || ""), "result-state"));
    for (const item of list(checkpoint.info)) {
      const line = node("p", item.testo, "check-info");
      line.append(node("span", " · " + item.fonte, "field-source"));
      out.push(line);
    }
    if (!out.length) out.push(node("p", "Nessuna correzione: lista coerente con quanto detto.", "result-state"));
    return out;
  });
}

function sendProfile(payload) {
  if (!activeMic(snapshot) || mutating) return;
  $("recipient-panel").hidden = true;
  $("recipient-chip").setAttribute("aria-expanded", "false");
  mutateSessionAction("profilo_destinatario", payload);
}

let lastStep = null;
const stepNames = new Map([["bisogno", "Bisogno"], ["inquadramento", "Domande"], ["proposta", "Prodotto"],
  ["complemento", "Complemento"], ["offerta", "Offerta"]]);

function renderVendita(view, results) {
  const steps = list(view?.steps).filter(item => stepNames.has(item?.key));
  refreshPart("sales-step-list", [steps], () => steps.map(item => {
    const li = node("li", stepNames.get(item.key), ["done", "current", "blocked"].includes(item.state) ? item.state : "");
    if (item.state === "current") li.setAttribute("aria-current", "step");
    return li;
  }));
  $("sales-step-reason").textContent = typeof view?.reason === "string" ? view.reason : "";
  const skippable = ["inquadramento", "complemento"].includes(view?.step);
  $("skip-step").hidden = !skippable;
  $("skip-step").disabled = mutating;

  const flags = list(view?.red_flags).filter(item => typeof item?.text === "string");
  $("alarm").hidden = !flags.length;
  document.querySelector("main").classList.toggle("alarm-active", flags.length > 0);
  refreshPart("alarm-list", [flags], () => flags.map(item =>
    node("li", item.text + (item.matched ? " · «" + item.matched + "»" : ""))));
  $("alarm-handled").disabled = mutating;

  const questions = list(view?.questions).filter(item => typeof item?.text === "string");
  const answered = list(view?.answered).filter(item => typeof item?.text === "string");
  // Once a product is confirmed the questions are behind us: give the room to complement and offer.
  $("questions-zone").hidden = (!questions.length && !answered.length) || Boolean(snapshot?.product?.confirmed_code);
  refreshPart("questions", [questions, answered], () => [
    ...questions.map(item => {
      const li = node("li", item.text);
      if (item.source) li.append(node("span", item.source, "source"));
      return li;
    }),
    ...answered.map(item => node("li", item.text, "answered"))
  ]);

  const hint = view?.semantic_hint;
  $("semantic-hint").hidden = !hint?.name;
  refreshPart("semantic-hint", [hint], () => {
    if (!hint?.name) return [];
    const ask = node("button", "Sì, usa questo bisogno", "small-button");
    ask.type = "button";
    ask.addEventListener("click", () => mutateSessionAction("accetta_suggerimento", {}));
    return [node("span", "Intendeva: " + hint.name + "?"), ask];
  });

  const excluded = list(view?.excluded).filter(item => typeof item?.name === "string");
  $("excluded").hidden = !excluded.length;
  $("excluded").textContent = excluded.length
    ? "Esclusi: " + excluded.map(item => item.name + " (" + (item.reason || "non ammissibile") + ")").join(" · ") : "";

  const confirmed = snapshot?.product?.confirmed_code;
  const complement = view?.complement;
  const decision = view?.complement_decision;
  refreshPart("complement", [complement, decision, confirmed, mutating], () => {
    if (!confirmed || !complement) return [];
    const card = node("div", "", "complement-card linked-card focus");
    const head = node("div", "", "card-line");
    head.append(node("strong", complement.name || complement.shelf || "Complemento", "card-name truncate"),
      node("span", prices(complement.price_cents) || (complement.shelf && !complement.code ? "scaffale" : "—"), "card-price"));
    card.append(head);
    const labels = node("span", "", "row-labels");
    labels.append(node("span", complement.level_label || "Complemento approvato",
      complement.reviewed === false ? "label warn level" : "label level"));
    if (complement.reviewed === false) labels.append(node("span", "valuta tu", "label warn"));
    if (complement.origin_kind === "sintomo" && symptomNames(complement).length) {
      labels.prepend(node("span", "per: " + symptomNames(complement).join(", "), "label symptom"));
    }
    if (Number.isInteger(complement.stock)) labels.append(node("span", "giacenza " + complement.stock, "label"));
    card.append(labels);
    if (complement.reason) card.append(node("span", complement.reason, "rank-reason"));
    if (complement.exclusions) card.append(node("span", "Escludere se: " + complement.exclusions, "result-facts"));
    if (decision) {
      card.append(node("span", decision === "accettato" ? "Accettato" : decision === "rifiutato" ? "Rifiutato" : "Saltato",
        "label decision"));
      return [card];
    }
    const actions = node("div", "", "actions");
    const accept = node("button", complement.code ? "Accettato · al carrello" : "Accettato", "small-button primary");
    accept.type = "button";
    accept.disabled = mutating;
    accept.addEventListener("click", () => mutateSessionAction("complemento", {decision: "accettato"}));
    const refuse = node("button", "Rifiutato", "small-button");
    refuse.type = "button";
    refuse.disabled = mutating;
    refuse.addEventListener("click", () => mutateSessionAction("complemento", {decision: "rifiutato"}));
    actions.append(accept, refuse);
    card.append(actions);
    return [card];
  });
  $("supplement-section").hidden = true;
  $("complement-empty").hidden = view?.complement_empty !== true;
  if (confirmed) $("propose-link").href = "/farmaco#" + encodeURIComponent(confirmed);
  if (view?.step !== lastStep && view?.step === "complemento") $("complement").scrollIntoView({block: "nearest"});
  lastStep = view?.step;

  const checkInfo = list(snapshot?.checkpoint?.info).filter(item => item?.per_cliente === true)
    .map(item => item?.testo).filter(text => typeof text === "string");
  const advice = [...new Set([...list(view?.advice).filter(item => typeof item === "string"), ...checkInfo])].slice(0, 6);
  const follow = typeof view?.follow_up === "string" ? view.follow_up : "";
  $("advice-zone").hidden = !advice.length && !follow;
  refreshPart("advice", [advice, follow], () => [
    ...advice.map(text => node("li", text)), ...(follow ? [node("li", "Quando tornare: " + follow)] : [])
  ]);
}


function updateControls() {
  $("listen").disabled = mutating || !reachable;
  $("reset").disabled = mutating || (!snapshot && !pendingReset);
  $("open-cart").disabled = !reachable;
  $("open-settings").disabled = !reachable;
}

function clearView() {
  resetResultState();
  closeSources();
  renderKeys.clear();
  render(null);
}

function applySnapshot(data, replaceSession = false) {
  if (!isSnapshot(data)) return false;
  reachable = true;
  if (snapshot && !replaceSession) {
    if (data.session_id !== snapshot.session_id || data.version <= snapshot.version) return false;
  } else if (!replaceSession && activeMic(data)) {
    foreignSession = true;
    render(null);
    return false;
  }
  if (snapshot?.session_id !== data.session_id) {
    resetResultState();
    closeSources();
    renderKeys.clear();
    if (activeMic(snapshot)) abandoned = snapshot.session_id;
  }
  pendingReset = null;
  foreignSession = false;
  snapshot = data;
  render(snapshot);
  return true;
}

function actionBody(state, action) {
  return {session_id: state.session_id, expected_action_version: state.action_version, action, payload: {}};
}

async function mutateSessionAction(action, payload) {
  if (mutating || pageClosed || !snapshot || foreignSession) return;
  mutating = true;
  updateControls();
  try {
    await pollRequest;
    if (pageClosed || !snapshot || foreignSession) return;
    const body = actionBody(snapshot, action);
    body.payload = payload;
    const response = await request("azione", body);
    if (pageClosed) return;
    if (response.status === 409) {
      if (isSnapshot(response.data)) inspectStatus(response.data);
      $("message").textContent = "La sessione è cambiata. Controlla il carrello e ripeti l’azione.";
      return;
    }
    if (!response.ok || !isSnapshot(response.data)) {
      const detail = typeof response.data?.errore === "string" ? response.data.errore : "";
      $("message").textContent = detail || "Azione non applicata. Controlla la confezione e riprova.";
      return;
    }
    if (!applySnapshot(response.data)) {
      $("message").textContent = "Lo stato è stato aggiornato altrove. Controlla i dati prima di riprovare.";
      return;
    }
    $("message").textContent = "";
  } catch {
    if (!pageClosed) $("message").textContent = "Collegamento al banco non disponibile. L’azione non è stata confermata.";
  } finally {
    mutating = false;
    updateControls();
    if (snapshot && !pageClosed) render(snapshot);
  }
}

function disconnect() {
  const previous = snapshot || pendingReset;
  if (previous) {
    abandoned = previous.session_id;
    request("azione", actionBody(previous, "termina"), true).catch(() => {});
  }
  snapshot = null;
  pendingReset = null;
  foreignSession = false;
  reachable = false;
  clearView();
  $("message").textContent = "Collegamento perso. La trascrizione e le schede sono state rimosse.";
}

function inspectStatus(data) {
  if (!isSnapshot(data)) throw new Error("snapshot");
  if (!reachable) {
    $("message").textContent = abandoned ? "Collegamento ripristinato. I contenuti precedenti sono stati rimossi." : "";
  }
  reachable = true;
  if (snapshot && snapshot.session_id !== data.session_id) {
    snapshot = null;
    foreignSession = activeMic(data);
    clearView();
    $("message").textContent = "La sessione è cambiata. I contenuti precedenti sono stati rimossi.";
    if (foreignSession) return;
  }
  if (pendingReset?.session_id === data.session_id || !snapshot && data.session_id === abandoned) {
    pendingReset = {session_id: data.session_id, action_version: data.action_version};
    foreignSession = false;
    return render(null);
  }
  if (pendingReset && pendingReset.session_id !== data.session_id) pendingReset = null;
  if (applySnapshot(data) && data.status?.error_code) showMicError();
}

function showMicError() {
  if (snapshot?.status?.error_code === "dispositivo_input_non_disponibile") {
    $("message").textContent = "Il microfono selezionato non è disponibile. Apri Impostazioni, scegli un ingresso audio o il predefinito del sistema e salva prima di riprovare.";
    return;
  }
  $("message").textContent = "Controlla il microfono predefinito di Windows e il modello vocale, poi riprova.";
}

function settingsMessage(message) {
  $("settings-status").textContent = message;
}

function updateSettingsControls() {
  const remote = $("settings-provider").value === "openai";
  $("settings-remote").hidden = !remote;
  $("settings-model").required = remote;
  $("settings-key").disabled = settingsBusy || !remote || $("settings-clear-key").checked;
  $("settings-clear-label").hidden = !settings?.api_key_configured;
  const speechEngine = $("settings-speech-engine");
  speechEngine.disabled = settingsBusy || !settings;
  speechEngine.querySelector('option[value="whisper.cpp"]').disabled = !settings?.whisper_available;
  $("settings-input-device").disabled = settingsBusy || !settings;
  for (const id of ["settings-provider", "settings-threshold", "settings-model", "settings-clear-key", "settings-enabled", "settings-save"]) {
    $(id).disabled = settingsBusy || !settings;
  }
  $("settings-check").disabled = settingsBusy || !remote || settings?.provider !== "openai" || !settings.api_key_configured;
  updateSpeechStatus();
  updateInputDeviceStatus();
}

function inputDeviceId(value) {
  return value == null || value === "" ? "" : String(value);
}

function inputDevicePayload(value) {
  if (value === "") return null;
  return /^\d+$/.test(value) ? Number(value) : value;
}

function updateInputDeviceStatus() {
  const status = $("settings-input-status");
  if (!settings) {
    status.textContent = inputDeviceNotice;
    return;
  }
  const selected = $("settings-input-device").value;
  const available = settings.input_devices.some(device => inputDeviceId(device.id) === selected);
  status.textContent = [
    inputDeviceNotice,
    settings.input_device_missing ? "Il microfono salvato non è disponibile. Scegli un ingresso o salva il predefinito del sistema." : "",
    selected && !available ? "Il microfono salvato non è disponibile. Scegli un altro ingresso o il predefinito." : "",
    settings.input_devices.length === 0 ? "Nessun ingresso audio è stato elencato. Puoi provare il predefinito del sistema." : "",
    "La scelta si applica al prossimo avvio dell’ascolto."
  ].filter(Boolean).join(" ");
}

function renderInputDevices(value) {
  const select = $("settings-input-device");
  const devices = Array.isArray(value.input_devices) ? value.input_devices.filter(device =>
    device && (typeof device.id === "string" && device.id || Number.isInteger(device.id) && device.id >= 0)
      && typeof device.name === "string" && device.name.trim()
      && Number.isInteger(device.channels) && device.channels > 0) : [];
  const selected = inputDeviceId(value.input_device);
  const seen = new Set();
  const defaultOption = node("option", "Predefinito del sistema");
  defaultOption.value = "";
  select.replaceChildren(defaultOption);
  for (const device of devices) {
    const id = inputDeviceId(device.id);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const option = document.createElement("option");
    option.value = id;
    option.textContent = device.default === true ? device.name + " · predefinito" : device.name;
    select.append(option);
  }
  if (selected && !seen.has(selected)) {
    const missing = document.createElement("option");
    missing.value = selected;
    missing.textContent = "Microfono salvato non disponibile";
    missing.disabled = true;
    select.append(missing);
  }
  select.value = selected;
  return devices;
}

function updateSpeechStatus() {
  if (!settings) {
    $("settings-speech-status").textContent = "";
    return;
  }
  const selected = $("settings-speech-engine").value;
  const speechNames = {vosk: "Vosk", "whisper.cpp": "Whisper.cpp", ibrido: "Ibrido · Vosk + Whisper.cpp"};
  const selectedName = speechNames[selected] || "Vosk";
  const activeName = speechNames[settings.speech_active_engine] || null;
  $("settings-speech-status").textContent = [
    settings.whisper_available ? "Whisper.cpp disponibile" : selected === "ibrido"
      ? "Whisper.cpp non disponibile; l’ibrido userà solo Vosk" : "Whisper.cpp non disponibile; Vosk resta disponibile",
    "Configurato per il prossimo ascolto: " + selectedName,
    activeName ? "Motore nella sessione corrente: " + activeName : "",
    activeName && activeName !== selectedName ? "La scelta salvata si applica al prossimo ascolto" : ""
  ].filter(Boolean).join(" · ");
}

function showSettings(value) {
  if (!value || !["local", "openai"].includes(value.provider) || !Number.isInteger(value.word_threshold)
      || typeof value.model !== "string" || typeof value.api_key_configured !== "boolean"
      || value.speech_engine != null && !["vosk", "whisper.cpp", "ibrido"].includes(value.speech_engine)
      || value.whisper_available != null && typeof value.whisper_available !== "boolean"
      || value.speech_active_engine != null && typeof value.speech_active_engine !== "string") {
    throw Error("invalid settings");
  }
  settings = {provider: value.provider, api_key_configured: value.api_key_configured,
    speech_engine: value.speech_engine || "vosk", whisper_available: value.whisper_available === true,
    speech_active_engine: value.speech_active_engine || null,
    input_device: value.input_device ?? null, input_device_missing: value.input_device_missing === true,
    input_devices: renderInputDevices(value)};
  inputDeviceNotice = "";
  $("settings-provider").value = value.provider;
  $("settings-speech-engine").value = settings.speech_engine;
  $("settings-model").value = value.model;
  $("settings-threshold").value = value.word_threshold;
  $("settings-enabled").checked = value.enabled === true;
  $("settings-key").value = "";
  $("settings-clear-key").checked = false;
  $("settings-key-state").textContent = value.api_key_configured ? "Chiave configurata" : "Nessuna chiave configurata";
  updateSpeechStatus();
}

async function openSettings() {
  if (settingsBusy) return;
  settings = null;
  settingsBusy = true;
  $("settings-key").value = "";
  $("settings-key-state").textContent = "";
  settingsMessage("Caricamento impostazioni…");
  updateSettingsControls();
  $("settings-dialog").showModal();
  try {
    const response = await fetch("/api/impostazioni", {cache: "no-store", signal: AbortSignal.timeout(6000)});
    if (!response.ok) throw Error("settings unavailable");
    showSettings(await response.json());
    settingsMessage("");
  } catch {
    settingsMessage("Impostazioni non disponibili.");
  } finally {
    settingsBusy = false;
    updateSettingsControls();
  }
}

async function saveSettings(event) {
  event.preventDefault();
  if (settingsBusy || !settings) return;
  const provider = $("settings-provider").value;
  const clear = $("settings-clear-key").checked;
  const payload = {
    provider,
    speech_engine: $("settings-speech-engine").value,
    input_device: inputDevicePayload($("settings-input-device").value),
    model: $("settings-model").value.trim(),
    word_threshold: Number($("settings-threshold").value),
    enabled: provider === "openai" && $("settings-enabled").checked && !clear
  };
  const key = provider === "openai" ? $("settings-key").value.trim() : "";
  if (payload.enabled && !key && !settings.api_key_configured) {
    settingsMessage("Inserisci la chiave API per attivare OpenAI.");
    return;
  }
  if (clear) payload.clear_api_key = true;
  else if (key) payload.api_key = key;
  $("settings-key").value = "";
  settingsBusy = true;
  updateSettingsControls();
  settingsMessage("Salvataggio…");
  try {
    const response = await request("impostazioni", payload);
    if (!response.ok) throw Error("save settings failed");
    showSettings(response.data);
    settingsMessage("Impostazioni salvate. Il microfono scelto sarà usato dal prossimo ascolto.");
  } catch {
    settingsMessage("Salvataggio non riuscito. Controlla i valori e riprova.");
  } finally {
    settingsBusy = false;
    updateSettingsControls();
  }
}

async function verifySettings() {
  if (settingsBusy || $("settings-check").disabled) return;
  settingsBusy = true;
  updateSettingsControls();
  settingsMessage("Verifica con testo di prova…");
  try {
    const response = await request("impostazioni/verifica", {});
    const messages = {
      chiave_assente: "Chiave API assente.",
      timeout: "Il provider non ha risposto in tempo.",
      provider_non_disponibile: "Il provider non è disponibile.",
      risposta_non_valida: "Il provider ha restituito una risposta non valida."
    };
    settingsMessage(response.ok && response.data?.ok === true ? "Connessione verificata."
      : messages[response.data?.code] || "Verifica non riuscita.");
  } catch {
    settingsMessage("Verifica non riuscita.");
  } finally {
    settingsBusy = false;
    updateSettingsControls();
  }
}

async function poll() {
  if (!pageClosed && !mutating) {
    const body = snapshot ? {session_id: snapshot.session_id} : {};
    pollRequest = (async () => {
      try {
        const response = await request("stato", body);
        if (pageClosed) return;
        if (!response.ok) throw new Error("status");
        inspectStatus(response.data);
      } catch {
        if (!pageClosed) {
          reportError("stato");
          disconnect();
        }
      }
    })();
    await pollRequest;
    pollRequest = null;
  }
  if (!pageClosed) setTimeout(poll, 350);
}

async function operate(route, body) {
  if (mutating || pageClosed) return;
  mutating = true;
  updateControls();
  $("message").textContent = "";
  try {
    await pollRequest;
    if (pageClosed) return;
    if (body.session_id && body.session_id !== (snapshot || pendingReset)?.session_id) {
      $("message").textContent = "La sessione è cambiata. Ripeti l’azione nella sessione corrente.";
      return;
    }
    const discarded = snapshot;
    if (discarded) {
      abandoned = discarded.session_id;
      pendingReset = {session_id: discarded.session_id, action_version: discarded.action_version};
      snapshot = null;
    }
    clearView();
    const response = await request(route, body);
    if (pageClosed) return;
    if (response.status === 409) {
      inspectStatus(response.data);
      $("message").textContent = "La sessione è cambiata. Controlla lo stato e ripeti l’azione.";
      return;
    }
    if (!response.ok && !isSnapshot(response.data)) {
      $("message").textContent = "Il banco non ha applicato l’azione. Riprova.";
      return;
    }
    if (!applySnapshot(response.data, true)) throw new Error("snapshot");
    abandoned = null;
    if (!response.ok || snapshot.status?.error_code) showMicError();
  } catch {
    if (!pageClosed) {
      reportError(route === "inizia" ? "microfono" : "azione");
      disconnect();
    }
  } finally {
    mutating = false;
    updateControls();
  }
}

$("listen").addEventListener("click", () => {
  if (activeMic(snapshot)) return operate("azione", actionBody(snapshot, "termina"));
  operate("inizia", {});
});
$("open-cart").addEventListener("click", () => {
  renderCart(snapshot?.cart || {items: [], item_count: 0, total_cents: 0, partial: false});
  if (!$('cart-dialog').open) $('cart-dialog').showModal();
});
$("reset").addEventListener("click", () => {
  const previous = pendingReset || snapshot;
  if (previous) operate("azione", actionBody(previous, "reset"));
});
$("correct-name").addEventListener("click", () => {
  if (!correctionCandidates.size) return;
  $("correction-dialog").showModal();
  renderResults(activeMic(snapshot) ? snapshot.desk_results : null);
});
$("correction-dialog").addEventListener("close", () => {
  if ($("correction-dialog").open) return;
  $("correction-options").replaceChildren();
  renderKeys.delete("correction-options");
});
$("open-settings").addEventListener("click", openSettings);
$("settings-input-device").addEventListener("change", updateInputDeviceStatus);
$("settings-speech-engine").addEventListener("change", updateSettingsControls);
$("settings-provider").addEventListener("change", updateSettingsControls);
$("settings-clear-key").addEventListener("change", updateSettingsControls);
$("settings-form").addEventListener("submit", saveSettings);
$("settings-check").addEventListener("click", verifySettings);
$("settings-close").addEventListener("click", () => $("settings-dialog").close());
$("settings-dialog").addEventListener("close", () => {
  $("settings-key").value = "";
});

window.addEventListener("pagehide", () => {
  pageClosed = true;
  const previous = snapshot || pendingReset;
  snapshot = null;
  pendingReset = null;
  clearView();
  if (previous) request("azione", actionBody(previous, "termina"), true).catch(() => {});
});
window.addEventListener("pageshow", event => {
  if (event.persisted) location.reload();
});
window.addEventListener("resize", () => renderResults(activeMic(snapshot) ? snapshot.desk_results : null));
$("sources-dialog").addEventListener("close", () => {
  if (!$("sources-dialog").open) {
    openedSources = null;
    $("sources-content").replaceChildren();
  }
});

poll();

$("check-toggle").addEventListener("click", () => {
  const open = $("check-panel").hidden;
  $("check-panel").hidden = !open;
  $("check-toggle").setAttribute("aria-expanded", String(open));
});
$("recipient-chip").addEventListener("click", () => {
  const open = $("recipient-panel").hidden;
  $("recipient-panel").hidden = !open;
  $("recipient-chip").setAttribute("aria-expanded", String(open));
});
for (const button of document.querySelectorAll("#recipient-panel [data-profile]")) {
  button.addEventListener("click", () => {
    try { sendProfile(JSON.parse(button.dataset.profile)); } catch { /* malformed preset */ }
  });
}
$("recipient-age").addEventListener("submit", event => {
  event.preventDefault();
  const years = Number.parseInt($("recipient-years").value, 10);
  const months = Number.parseInt($("recipient-months").value, 10);
  if (Number.isInteger(months) && months >= 0 && months < 36) {
    sendProfile({kind: "altra_persona", age_months: months, age_years: Math.floor(months / 12)});
  } else if (Number.isInteger(years) && years >= 0 && years <= 120) {
    sendProfile({kind: "altra_persona", age_years: years});
  }
  $("recipient-years").value = $("recipient-months").value = "";
});
$("recipient-reset").addEventListener("click", () => sendProfile({azzera: true}));

const TRANSCRIPT_KEY = "banco.trascrizione.ridotta";
function setTranscriptCollapsed(collapsed) {
  $("transcript-panel").classList.toggle("collapsed", collapsed);
  $("toggle-transcript").textContent = collapsed ? "Mostra" : "Riduci";
  $("toggle-transcript").setAttribute("aria-expanded", String(!collapsed));
}
try { setTranscriptCollapsed(localStorage.getItem(TRANSCRIPT_KEY) === "1"); } catch { setTranscriptCollapsed(false); }
$("toggle-transcript").addEventListener("click", () => {
  const collapsed = !$("transcript-panel").classList.contains("collapsed");
  setTranscriptCollapsed(collapsed);
  try { localStorage.setItem(TRANSCRIPT_KEY, collapsed ? "1" : "0"); } catch { /* storage unavailable: keep in memory */ }
});
fetch("/api/interfaccia", {cache: "no-store"}).then(response => response.ok ? response.json() : null).then(data => {
  const hidden = data?.mostra_trascrizione === false;
  $("transcript-panel").hidden = hidden;
  document.body.classList.toggle("no-transcript", hidden);
}).catch(() => {});
$("skip-step").addEventListener("click", () => {
  const step = snapshot?.vendita?.step;
  if (["inquadramento", "complemento"].includes(step)) mutateSessionAction("salta_passo", {step});
});
$("alarm-handled").addEventListener("click", () => mutateSessionAction("allarme_gestito", {}));
document.addEventListener("keydown", event => {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest("input, select, textarea, dialog[open]")) {
    if (event.key === "Escape" && openedSources) closeSources();
    return;
  }
  const key = event.key.toLowerCase();
  if (event.key === "Escape") {
    if (openedSources) closeSources();
    else if (selectedCode) { resetSelection(); renderResults(snapshot?.desk_results); }
    return;
  }
  if (!activeMic(snapshot) || mutating) return;
  const rows = [...document.querySelectorAll("#products .result-row")];
  if (["1", "2", "3"].includes(key)) {
    const button = rows[Number(key) - 1]?.querySelector(".result-select");
    if (button) { event.preventDefault(); button.click(); }
  } else if (key === "n") {
    const button = (document.querySelector("#products .result-row.selected") || rows[0])
      ?.querySelector(".not-relevant:not(:disabled)");
    if (button) { event.preventDefault(); button.click(); }
  } else if (key === "s" && !$("skip-step").hidden) {
    event.preventDefault();
    $("skip-step").click();
  }
});
