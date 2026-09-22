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

let selectedRowLabel = null;
let lastStage1Matches = [];
let lastThreshold = 0.5;

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
  for (const m of matches) {
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
  stage2Meta.innerHTML = "";
  const specBadge = document.createElement("span");
  specBadge.className = "badge " + (data.ministerial_spec_found ? "ok" : "off");
  specBadge.textContent = data.ministerial_spec_found
    ? `貨物等省令 ${data.ministerial_spec_article} を反映`
    : "貨物等省令: 対応条文なし";
  stage2Meta.appendChild(specBadge);

  const kaishakuBadge = document.createElement("span");
  kaishakuBadge.className = "badge " + (data.kaishaku_found ? "ok" : "off");
  kaishakuBadge.textContent = data.kaishaku_found
    ? `用語解釈PDF ${data.kaishaku_term_count}語を反映`
    : "用語解釈PDF: 対応なし";
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

  for (const m of data.subitems) {
    const pct = Math.round(m.probability * 100);
    const hit = m.probability >= data.threshold && !m.suppressed;
    const row = document.createElement("div");
    row.className = "item-row";

    let tag = "";
    if (m.suppressed) {
      tag = `<span class="tag suppressed">除外規定で抑制</span>`;
    } else if (hit) {
      tag = `<span class="tag hit">該当候補</span>`;
    }
    const reviewTag = m.needs_manual_review
      ? `<span class="tag review">要目視確認</span>`
      : "";

    row.innerHTML = `
      <div class="item-head">
        <span class="label">${escapeHtml(m.label)}</span>
        ${tag}
        ${reviewTag}
        <span class="pct">${pct}%</span>
      </div>
    `;
    if (m.suppressed && m.suppressed_reason) {
      const reason = document.createElement("div");
      reason.className = "reason";
      reason.textContent = m.suppressed_reason;
      row.appendChild(reason);
    }
    stage2Results.appendChild(row);
  }
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
  setStatus(stage1Status, "Stage1: 全17項を判定中...（TypeSafe AIを呼び出しています）");
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

runBtn.addEventListener("click", runStage1);
clearBtn.addEventListener("click", () => {
  descriptionEl.value = "";
  stage1Panel.hidden = true;
  stage2Panel.hidden = true;
  setError(stage1Error, null);
  setError(stage2Error, null);
  selectedRowLabel = null;
});
descriptionEl.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    runStage1();
  }
});
