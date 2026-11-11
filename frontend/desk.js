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
  refreshPart("transcript", [text, partialStart, cuts, evidence], () => {
    return cuts.slice(1).map((end, index) => {
      const start = cuts[index];
      const found = evidence.filter(({span}) => span.start < end && span.end > start);
      const item = node(found.length ? "mark" : "span", text.slice(start, end));
      if (start >= partialStart) item.classList.add("partial");
      if (found.length) {
        item.classList.add("highlight");
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
  $("open-cart").textContent = "Carrello · " + itemCount + " · " + cartTotalText(cart);

  const strip = items.map(item => [item.code, cartRowName(item)]);
  $("cart-strip").hidden = !items.length;
  refreshPart("cart-strip-items", [strip, mutating], () => items.map(item => {
    const line = node("li", "", "cart-strip-item");
    line.append(node("span", item.name || item.display?.name || item.code));
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

function resultRow(row, selected, option, preference, preferredCode = null) {
  const product = selected ? productFor(row, preferredCode) : row;
  const article = node("article", "", "result-row");
  if (option || preference) article.classList.add("voice-match");
  const offer = offerDetails(row.offer);
  const select = node("button", "", "result-select");
  select.type = "button";
  select.setAttribute("aria-pressed", String(selected));
  const percentage = row.affinity_percent;
  const affinity = Number.isFinite(percentage) && percentage >= 0 && percentage <= 100
    ? "Affinità documentale " + percentage + "%" : null;
  const note = node("span", "", "relevance");
  if (affinity) note.append(node("span", affinity, "affinity"));
  if (offer) note.append(node("span", offer.demo ? "Offerta di prova" : "In offerta"));
  else if (!affinity) note.append(node("span", row.relevance || "Nome rilevato"));
  if (option) note.append(node("span", "Possibile scelta", "voice-marker"));
  else if (preference) note.append(node("span", "Forma richiesta", "voice-marker"));
  const identity = node("span", "", "result-identity");
  const title = node("strong", product.display.name, "truncate");
  title.title = product.display.name;
  identity.append(title);
  const facts = (offer ? [offer.benefit, offer.price, offer.validity]
    : [compactFacts(product.display), list(row.symptoms).filter(Boolean).join(", ")]).filter(Boolean).join(" · ");
  if (facts) {
    const details = node("span", facts, "result-facts truncate");
    details.title = facts;
    identity.append(details);
  }
  select.append(note, identity);
  const key = rowKey(row);
  select.addEventListener("click", () => {
    const source = selected && selectedByVoice ? "voice" : "row";
    selectProduct(row, product.code, source);
    [...document.querySelectorAll(".result-select")].find(button => button.dataset.row === key)?.focus();
  });
  select.dataset.row = key;
  article.append(select);

  const variants = variantsFor(row);
  if (variants.length > 1) {
    const options = node("select", "", "variants");
    options.setAttribute("aria-label", "Confezione di " + row.display.name);
    options.dataset.row = key;
    const chosenCode = selected && selectedVariantSource !== "row" ? selectedVariant : "";
    options.append(node("option", "Scegli confezione"));
    options.lastChild.value = "";
    options.lastChild.disabled = true;
    for (const variant of variants) {
      const option = node("option", variant.label || variant.display.package_label || variant.display.name);
      option.value = variant.code;
      options.append(option);
    }
    options.value = chosenCode || "";
    options.addEventListener("change", () => {
      selectProduct(row, options.value, "variant");
      [...document.querySelectorAll(".variants")].find(menu => menu.dataset.row === key)?.focus();
    });
    article.append(options);
  }
  const ambiguousVoice = list(snapshot?.desk_results?.voice_options).length > 1;
  const explicitlySelected = selected && rowKey(row) === selectedCode && variants.some(item => item.code === selectedVariant)
    && (["voice", "variant", "preferred"].includes(selectedVariantSource)
      || selectedVariantSource === "row" && variants.length === 1);
  const canAdd = !ambiguousVoice && variants.length === 1 || explicitlySelected;
  const addCode = variants.length === 1 ? variants[0].code : canAdd ? selectedVariant : null;
  const add = node("button", canAdd ? "Aggiungi al carrello" : "Scegli confezione", "cart-add");
  add.type = "button";
  add.disabled = !canAdd || mutating;
  add.setAttribute("aria-label", canAdd
    ? "Aggiungi " + (variants.find(item => item.code === addCode)?.display?.name || product.display.name) + " al carrello"
    : "Scegli una confezione prima di aggiungerla al carrello");
  add.addEventListener("click", () => {
    if (addCode) mutateSessionAction("aggiungi_carrello", {code: addCode});
  });
  article.append(add);

  const isCheckout = snapshot?.desk_phase?.key === "closing"
    || snapshot?.desk_results?.phase === "closing";
  const offerCode = row.offer?.codice || row.offer?.offer_code || row.offer?.code;
  const inCart = cartItems(snapshot?.cart).some(item => item.code === product.code);
  if (row.section === "offers" && offer && isCheckout && inCart && typeof offerCode === "string" && offerCode) {
    const applyOffer = node("button", "Applica offerta", "apply-offer");
    applyOffer.type = "button";
    applyOffer.disabled = mutating;
    applyOffer.setAttribute("aria-label", "Applica l’offerta a " + product.display.name);
    applyOffer.addEventListener("click", () => mutateSessionAction("applica_offerta", {
      code: product.code, offer_code: offerCode
    }));
    article.append(applyOffer);
  }
  if (list(row.references).some(item => safeHttpsUrl(item?.source?.url))
      || list(product.display.sources).some(item => safeHttpsUrl(item?.url))
      || list(row.covered_symptoms).length || list(row.uncovered_symptoms).length
      || documentedEquivalents(product.display).length) {
    const details = node("button", "Fonti e dettagli", "sources-button");
    details.type = "button";
    details.setAttribute("aria-label", "Fonti e dettagli di " + product.display.name);
    details.addEventListener("click", () => showSources(row, product));
    article.append(details);
  }
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
    list(row.variants).map(item => [item.code, item.display, item.label])]);
  refreshPart(id, [key, selected && rowKey(selected), selectedVariant, selectedVariantSource,
    selectedByVoice, preferredCode, flags, mutating],
    () => visible.map((row, index) => resultRow(row, row === selected, ...flags[index], preferredCode)));
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
    products: compact ? 3 : offers.length && supplements.length ? 3 : offers.length || supplements.length ? 4 : 6,
    supplements: compact ? 1 : 2,
    offers: compact ? 1 : 2
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
  $("supplement-section").hidden = !supplements.length;
  $("offer-section").hidden = !offers.length;
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
  $("listen").textContent = recording ? "Termina ascolto" : "Inizia ascolto";

  const live = recording ? data : null;
  const evidence = currentEvidence(live);
  renderPhase(live?.desk_phase, evidence, live?.transcript, live?.recipient);
  renderTranscript(live?.transcript, evidence);
  renderResults(live?.desk_results);
  updateControls();
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
