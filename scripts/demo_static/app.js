const descriptionEl = document.getElementById("description");
const runBtn = document.getElementById("runBtn");
const clearBtn = document.getElementById("clearBtn");

const stage1Status = document.getElementById("stage1Status");
const stage1Error = document.getElementById("stage1Error");
const stage1Panel = document.getElementById("stage1Panel");
const stage1Results = document.getElementById("stage1Results");

const stage2Panel = document.getElementById("stage2Panel");
const stage2Title = document.getElementById("stage2Title");
const stage2Meta = document.getElementById("stage2Meta");
const stage2Status = document.getElementById("stage2Status");
const stage2Error = document.getElementById("stage2Error");
const stage2Results = document.getElementById("stage2Results");

const stage3Panel = document.getElementById("stage3Panel");
const stage3Title = document.getElementById("stage3Title");
const stage3Status = document.getElementById("stage3Status");
const stage3Error = document.getElementById("stage3Error");
const stage3Results = document.getElementById("stage3Results");
const stage3Verdict = document.getElementById("stage3Verdict");

let selectedRowLabel = null;
let lastStage1Matches = [];
let lastThreshold = 0.5;
let currentStage2Subitems = [];
let currentStage2Threshold = 0.5;
let currentStage3Criteria = [];
let currentStage3ItemId = null;
let stage3CombineMode = "OR";

function setStatus(el, text) {
  if (!text) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  el.innerHTML = `<span class="spinner"></span><span>${escapeHtml(text)}</span>`;
}

function setError(el, text) {
  if (!text) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = text;
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// "3_2" のような id（枝番）を [3, 2] のように数値配列化し、
// 項番号・号番号の自然な昇順（1, 2, 3, 3の2, 4, ...）で比較する。
function idSortKey(id) {
  return String(id).split("_").map((p) => parseInt(p, 10) || 0);
}
function compareIds(a, b) {
  const ka = idSortKey(a), kb = idSortKey(b);
  const len = Math.max(ka.length, kb.length);
  for (let i = 0; i < len; i++) {
    const va = ka[i] ?? 0, vb = kb[i] ?? 0;
    if (va !== vb) return va - vb;
  }
  return 0;
}

async function postJson(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

function renderStage1(matches, threshold) {
  lastStage1Matches = matches;
  lastThreshold = threshold;
  stage1Results.innerHTML = "";
  const sorted = [...matches].sort((a, b) => compareIds(a.row_id, b.row_id));
  for (const m of sorted) {
    const pct = Math.round(m.probability * 100);
    const hit = m.probability >= threshold;
    const row = document.createElement("div");
    row.className = "bar-row";
    row.dataset.rowLabel = m.label;
    row.innerHTML = `
      <div class="label${m.label === selectedRowLabel ? " selected" : ""}">${escapeHtml(m.label)}の項</div>
      <div class="bar-track"><div class="bar-fill${hit ? " hit" : ""}" style="width:${pct}%"></div></div>
      <div class="pct">${pct}%</div>
    `;
    row.addEventListener("click", () => runStage2(m.label));
    stage1Results.appendChild(row);
  }
}

function renderStage2(data) {
  currentStage2Subitems = data.subitems || [];
  currentStage2Threshold = data.threshold;
  stage2Meta.innerHTML = "";
  const specBadge = document.createElement("span");
  specBadge.className = "badge " + (data.matrix_spec_item_count > 0 ? "ok" : "off");
  specBadge.textContent = data.matrix_spec_item_count > 0
    ? `マトリクス表: 貨物等省令を${data.matrix_spec_item_count}号に反映`
    : "マトリクス表: 対応する貨物等省令条文なし";
  stage2Meta.appendChild(specBadge);

  const kaishakuBadge = document.createElement("span");
  kaishakuBadge.className = "badge " + (data.matrix_term_count > 0 ? "ok" : "off");
  kaishakuBadge.textContent = data.matrix_term_count > 0
    ? `マトリクス表: 用語解釈${data.matrix_term_count}件を反映`
    : "マトリクス表: 用語解釈なし";
  stage2Meta.appendChild(kaishakuBadge);

  stage2Results.innerHTML = "";
  if (data.note) {
    stage2Results.innerHTML = `<div class="empty">${escapeHtml(data.note)}</div>`;
    return;
  }
  if (!data.subitems || data.subitems.length === 0) {
    stage2Results.innerHTML = `<div class="empty">号への分解対象がありませんでした</div>`;
    return;
  }

  const sorted = [...data.subitems].sort((a, b) => compareIds(a.item_id, b.item_id));

  for (const m of sorted) {
    const group = document.createElement("div");
    group.className = "item-row";
    group.appendChild(renderNecessaryConditionRow(m, data.threshold));
    for (const excl of buildExclusionRows(m)) {
      group.appendChild(excl);
    }
    stage2Results.appendChild(group);
  }
}

// 「必要条件」行: 号自身の本文（実質テキスト）に対するJevの該当確率。
// 除外規定が発火しているかどうかとは無関係に、この号の本文自体が
// 該当するかどうかを表す一次判定。
function renderNecessaryConditionRow(m, threshold) {
  const pct = Math.round(m.probability * 100);
  const hit = m.probability >= threshold;
  const row = document.createElement("div");
  row.className = "cond-row";
  row.innerHTML = `
    <span class="cond-type-tag necessary">必要条件</span>
    <span class="cond-label">${escapeHtml(m.label)}</span>
    <span class="cond-text" title="${escapeHtml(m.text || "")}">${escapeHtml(m.text || "")}</span>
    <div class="bar-track cond-bar"><div class="bar-fill${hit ? " hit" : ""}" style="width:${pct}%"></div></div>
    <span class="pct">${pct}%</span>
  `;
  if (m.needs_manual_review) {
    const tag = document.createElement("span");
    tag.className = "tag review";
    tag.textContent = "要目視確認";
    row.appendChild(tag);
  }
  if (m.suppressed) {
    const tag = document.createElement("span");
    tag.className = "tag suppressed";
    tag.textContent = "除外規定により非該当";
    row.appendChild(tag);
  } else if (hit) {
    const tag = document.createElement("span");
    tag.className = "tag hit";
    tag.textContent = "該当候補";
    row.appendChild(tag);
  }

  const specBtn = document.createElement("button");
  specBtn.className = "spec-link";
  specBtn.textContent = "Stage3: 仕様を入力して判定 →";
  specBtn.addEventListener("click", () => runStage3(m.item_id));
  row.appendChild(specBtn);

  return row;
}

// 「除外規定」行: この号に付随する除外条件を、種別ごとに最小単位で
// 分割して1行ずつ表示する（他項番の除外／同一行内の他号の除外／
// 機械的に解決できない除外節、の3種類）。
function buildExclusionRows(m) {
  const rows = [];
  for (const rowId of m.excludes_rows || []) {
    rows.push(makeExclusionRow(m, `項${rowId}に該当する場合を除く`, isRowExclusionTriggered(rowId)));
  }
  for (const itemId of m.excludes_self_items || []) {
    rows.push(makeExclusionRow(m, `同じ行内の号（item_id=${itemId}）に該当する場合を除く`, isSiblingExclusionTriggered(itemId)));
  }
  if (m.raw_exclusion) {
    rows.push(makeExclusionRow(m, m.raw_exclusion, null));
  }
  return rows;
}

function isRowExclusionTriggered(rowId) {
  const match = lastStage1Matches.find((r) => r.row_id === rowId);
  if (!match) return null;
  return match.probability >= lastThreshold;
}

function isSiblingExclusionTriggered(itemId) {
  const sibling = (currentStage2Subitems || []).find((s) => s.item_id === itemId);
  if (!sibling) return null;
  return sibling.probability >= currentStage2Threshold;
}

function makeExclusionRow(m, text, triggered) {
  const row = document.createElement("div");
  row.className = "cond-row exclusion-row";
  let statusTag;
  if (triggered === null) {
    statusTag = `<span class="tag review">要目視確認</span>`;
  } else if (triggered) {
    statusTag = `<span class="tag suppressed">適用中（この号は非該当）</span>`;
  } else {
    statusTag = `<span class="tag off-tag">現時点では不適用</span>`;
  }
  row.innerHTML = `
    <span class="cond-type-tag exclusion">除外規定</span>
    <span class="cond-label">${escapeHtml(m.label)}</span>
    <span class="cond-text" title="${escapeHtml(text)}">${escapeHtml(text)}</span>
    <span class="cond-spacer"></span>
    ${statusTag}
  `;
  return row;
}

async function runStage1() {
  const description = descriptionEl.value.trim();
  if (!description) {
    setError(stage1Error, "製品・技術の説明を入力してください");
    return;
  }
  setError(stage1Error, null);
  setError(stage2Error, null);
  stage2Panel.hidden = true;
  selectedRowLabel = null;

  runBtn.disabled = true;
  setStatus(stage1Status, "Stage1: 全17項の製品カテゴリに属するか分類中...（TypeSafe AIを呼び出しています）");
  stage1Panel.hidden = true;

  try {
    const data = await postJson("/api/stage1", { description });
    stage1Panel.hidden = false;
    renderStage1(data.matches, data.threshold);
  } catch (e) {
    setError(stage1Error, "判定に失敗しました: " + e.message);
  } finally {
    setStatus(stage1Status, null);
    runBtn.disabled = false;
  }
}

async function runStage2(rowLabel) {
  const description = descriptionEl.value.trim();
  if (!description) return;

  selectedRowLabel = rowLabel;
  renderStage1(lastStage1Matches, lastThreshold);

  setError(stage2Error, null);
  stage3Panel.hidden = true;
  stage2Panel.hidden = false;
  stage2Title.textContent = `Stage2 — ${rowLabel}の項 を号単位で判定`;
  stage2Results.innerHTML = "";
  stage2Meta.innerHTML = "";
  setStatus(stage2Status, `${rowLabel}の項を号単位に分解して判定中...`);
  stage2Panel.scrollIntoView({ behavior: "smooth", block: "nearest" });

  try {
    const data = await postJson("/api/stage2", { description, row_label: rowLabel });
    renderStage2(data);
  } catch (e) {
    setError(stage2Error, "判定に失敗しました: " + e.message);
  } finally {
    setStatus(stage2Status, null);
  }
}

const COMPARATOR_TEXT = { ">=": "以上", "<=": "以下", ">": "を超える", "<": "未満" };
const COMPARATOR_SYMBOL = { ">=": "≥", "<=": "≤", ">": ">", "<": "<" };

function findStage2Item(itemId) {
  return (currentStage2Subitems || []).find((s) => s.item_id === itemId) || null;
}

async function runStage3(itemId) {
  if (!selectedRowLabel) return;
  currentStage3ItemId = itemId;

  setError(stage3Error, null);
  stage3Panel.hidden = false;
  stage3Results.innerHTML = "";
  stage3Verdict.innerHTML = "";
  setStatus(stage3Status, `${itemId}号の数値仕様条件を条文から抽出中...`);
  stage3Panel.scrollIntoView({ behavior: "smooth", block: "nearest" });

  try {
    const data = await postJson("/api/stage3", { row_label: selectedRowLabel, item_id: itemId });
    stage3Title.textContent = `Stage3 — ${data.label}（${data.item_id}）の数値仕様を入力`;
    currentStage3Criteria = (data.criteria || []).map((c, idx) => ({ ...c, id: idx, userValue: null, metState: null }));
    renderStage3();
  } catch (e) {
    setError(stage3Error, "抽出に失敗しました: " + e.message);
  } finally {
    setStatus(stage3Status, null);
  }
}

function requirementText(c) {
  const symbol = COMPARATOR_SYMBOL[c.comparator] || c.comparator;
  const unit = c.unit ? ` ${escapeHtml(c.unit)}` : "";
  return `条文の基準: <strong>${symbol} ${c.threshold}${unit}</strong>（${escapeHtml(c.matched_text || "")}）`;
}

function renderStage3() {
  stage3Results.innerHTML = "";

  if (currentStage3Criteria.length === 0) {
    stage3Results.innerHTML = `<div class="empty">この号には機械抽出可能な数値仕様条件が見つかりませんでした。Stage2の判定のみで確定です。</div>`;
    renderStage3Verdict();
    return;
  }

  for (const c of currentStage3Criteria) {
    const card = document.createElement("div");
    card.className = "criterion-card";

    const rawLine = document.createElement("div");
    rawLine.className = "raw-line";
    rawLine.textContent = c.raw_line;
    card.appendChild(rawLine);

    const inputRow = document.createElement("div");
    inputRow.className = "criterion-input-row";

    if (c.resolved) {
      inputRow.innerHTML = `
        <span class="param-label">${escapeHtml(c.parameter_label || "数値条件")}</span>
        <input type="number" step="any" placeholder="実測値">
        <span class="criterion-req">${requirementText(c)}</span>
      `;
      const input = inputRow.querySelector("input");
      input.addEventListener("input", () => {
        const v = input.value === "" ? null : parseFloat(input.value);
        c.userValue = v;
        c.metState = evaluateNumericCriterion(c, v);
        updateVerdictBadge(card, c);
        renderStage3Verdict();
      });
    } else {
      inputRow.innerHTML = `
        <span class="param-label">この条件に該当するか（原文参照）</span>
        <span class="bool-toggle">
          <button data-v="yes">該当する</button>
          <button data-v="no">該当しない</button>
        </span>
      `;
      const buttons = inputRow.querySelectorAll(".bool-toggle button");
      buttons.forEach((btn) => {
        btn.addEventListener("click", () => {
          const isYes = btn.dataset.v === "yes";
          c.userValue = isYes;
          c.metState = isYes;
          buttons.forEach((b) => b.classList.remove("active", "yes", "no"));
          btn.classList.add("active", isYes ? "yes" : "no");
          updateVerdictBadge(card, c);
          renderStage3Verdict();
        });
      });
    }

    const verdictSpan = document.createElement("span");
    verdictSpan.className = "criterion-verdict pending";
    verdictSpan.textContent = "未入力";
    inputRow.appendChild(verdictSpan);

    card.appendChild(inputRow);
    stage3Results.appendChild(card);
  }

  renderStage3Verdict();
}

function evaluateNumericCriterion(c, value) {
  if (value === null || Number.isNaN(value)) return null;
  if (c.comparator === ">=") return value >= c.threshold;
  if (c.comparator === "<=") return value <= c.threshold;
  if (c.comparator === ">") return value > c.threshold;
  if (c.comparator === "<") return value < c.threshold;
  return null;
}

function updateVerdictBadge(card, c) {
  const badge = card.querySelector(".criterion-verdict");
  if (c.metState === null) {
    badge.className = "criterion-verdict pending";
    badge.textContent = "未入力";
  } else if (c.metState) {
    badge.className = "criterion-verdict met";
    badge.textContent = "条件を満たす";
  } else {
    badge.className = "criterion-verdict unmet";
    badge.textContent = "条件を満たさない";
  }
}

function combineResults(criteria, mode) {
  if (criteria.length === 0) return true;
  const vals = criteria.map((c) => c.metState);
  if (mode === "OR") {
    if (vals.some((v) => v === true)) return true;
    if (vals.every((v) => v === false)) return false;
    return null;
  }
  // AND
  if (vals.some((v) => v === false)) return false;
  if (vals.every((v) => v === true)) return true;
  return null;
}

function renderStage3Verdict() {
  const box = document.createElement("div");

  const modeRow = document.createElement("div");
  modeRow.className = "row";
  modeRow.innerHTML = `
    <span class="hint">号内の複数条件の関係（原文からは自動判定できません）:</span>
    <button class="ghost" data-mode="OR">いずれか1つに該当（OR・既定）</button>
    <button class="ghost" data-mode="AND">すべてに該当（AND）</button>
  `;
  modeRow.querySelectorAll("button").forEach((btn) => {
    if (btn.dataset.mode === stage3CombineMode) btn.style.borderColor = "var(--accent)";
    btn.addEventListener("click", () => {
      stage3CombineMode = btn.dataset.mode;
      renderStage3Verdict();
    });
  });

  const specResult = combineResults(currentStage3Criteria, stage3CombineMode);
  const stage2Item = findStage2Item(currentStage3ItemId);
  const stage2Hit = !!stage2Item && stage2Item.probability >= currentStage2Threshold && !stage2Item.suppressed;

  let overall, headline, cls;
  if (specResult === null) {
    overall = "pending";
    cls = "pending";
    headline = "未確定（すべての条件に回答してください）";
  } else if (stage2Hit && specResult === true) {
    cls = "hit";
    headline = "該当（規制対象の可能性）";
  } else {
    cls = "miss";
    headline = "非該当";
  }

  const answeredCount = currentStage3Criteria.filter((c) => c.metState !== null).length;
  const specText = specResult === null ? "未確定" : (specResult ? "条件を満たす" : "条件を満たさない");

  const verdictBox = document.createElement("div");
  verdictBox.className = `final-verdict-box ${cls}`;
  verdictBox.innerHTML = `
    <div class="headline">${headline}</div>
    <div class="detail">
      Stage2判定: ${stage2Item ? Math.round(stage2Item.probability * 100) + "%" + (stage2Item.suppressed ? "（除外規定により抑制）" : "") : "―"}
      ／ 数値仕様（${stage3CombineMode === "OR" ? "OR" : "AND"}想定）: ${specText}
      （${answeredCount}/${currentStage3Criteria.length}件に回答済み）
    </div>
  `;

  stage3Verdict.innerHTML = "";
  stage3Verdict.appendChild(modeRow);
  stage3Verdict.appendChild(verdictBox);
}

runBtn.addEventListener("click", runStage1);
clearBtn.addEventListener("click", () => {
  descriptionEl.value = "";
  stage1Panel.hidden = true;
  stage2Panel.hidden = true;
  stage3Panel.hidden = true;
  setError(stage1Error, null);
  setError(stage2Error, null);
  setError(stage3Error, null);
  selectedRowLabel = null;
  currentStage3Criteria = [];
  currentStage3ItemId = null;
});
descriptionEl.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    runStage1();
  }
});
