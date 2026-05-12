const bootstrap = window.__TRPG_BOOTSTRAP__ || {};

function byId(id) {
  return document.getElementById(id);
}

const elements = {
  activeSpeaker: byId("activeSpeaker"),
  roundValue: byId("roundValue"),
  upcomingText: byId("upcomingText"),
  feedbackBox: byId("feedbackBox"),
  historyBox: byId("historyBox"),
  rulesOutput: byId("rulesOutput"),
  notebookEditor: byId("notebookEditor"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.detail || `Request failed: ${response.status}`);
  }
  return data;
}

function setBusy(isBusy) {
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = isBusy;
  });
}

function renderSnapshot(snapshot) {
  if (!snapshot || !snapshot.state) {
    return;
  }
  elements.activeSpeaker.textContent = snapshot.state.active_speaker || "(unknown)";
  elements.roundValue.textContent = String(snapshot.state.round || 0);
  elements.upcomingText.textContent = snapshot.upcoming || "";
  elements.historyBox.textContent = snapshot.history || "No dialogue history yet.";
}

function showFeedback(message, advanceMessage = "") {
  elements.feedbackBox.textContent = [message, advanceMessage].filter(Boolean).join("\n\n");
}

async function refreshSnapshot() {
  const snapshot = await api("/api/state", { method: "GET", headers: {} });
  renderSnapshot(snapshot);
}

function noAdvance() {
  return byId("noAdvanceCheckbox").checked;
}

function notebookParams() {
  return {
    actor_id: byId("notebookActorSelect").value,
    owner_id: byId("notebookOwnerSelect").value,
    notebook_name: byId("notebookNameSelect").value,
  };
}

async function runAction(action) {
  try {
    setBusy(true);
    await action();
  } catch (error) {
    showFeedback(String(error.message || error));
  } finally {
    setBusy(false);
  }
}

byId("refreshButton").addEventListener("click", () => runAction(async () => {
  await refreshSnapshot();
  showFeedback("状态已刷新。");
}));

byId("historyRefreshButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/history?window=20", { method: "GET", headers: {} });
  elements.historyBox.textContent = result.history || "No dialogue history yet.";
  showFeedback("共享历史已刷新。");
}));

byId("initButton").addEventListener("click", () => runAction(async () => {
  const orderValue = byId("orderInput").value.trim();
  const result = await api("/api/init", {
    method: "POST",
    body: JSON.stringify({ order: orderValue ? orderValue.split(",").map((item) => item.trim()).filter(Boolean) : [] }),
  });
  renderSnapshot(result.snapshot);
  showFeedback(result.message);
}));

byId("advanceButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/advance", { method: "POST", body: JSON.stringify({}) });
  renderSnapshot(result.snapshot);
  showFeedback(result.message);
}));

byId("setOrderButton").addEventListener("click", () => runAction(async () => {
  const order = byId("orderInput").value.split(",").map((item) => item.trim()).filter(Boolean);
  const result = await api("/api/set-order", {
    method: "POST",
    body: JSON.stringify({ order, reason: byId("orderReasonInput").value.trim() }),
  });
  renderSnapshot(result.snapshot);
  showFeedback(result.message);
}));

byId("humanTurnButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/turn/human", {
    method: "POST",
    body: JSON.stringify({ message: byId("humanMessage").value, no_advance: noAdvance() }),
  });
  renderSnapshot(result.snapshot);
  showFeedback(result.message, result.advance_message);
}));

byId("gmTurnButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/turn/gm", {
    method: "POST",
    body: JSON.stringify({
      message: byId("gmMessage").value,
      context: byId("gmContext").value,
      no_advance: noAdvance(),
    }),
  });
  renderSnapshot(result.snapshot);
  showFeedback(result.message, result.advance_message);
}));

byId("playerTurnButton").addEventListener("click", () => runAction(async () => {
  const actorId = byId("playerActorSelect").value;
  const result = await api(`/api/turn/player/${actorId}`, {
    method: "POST",
    body: JSON.stringify({
      message: byId("playerMessage").value,
      context: byId("playerContext").value,
      no_advance: noAdvance(),
    }),
  });
  renderSnapshot(result.snapshot);
  showFeedback(result.message, result.advance_message);
}));

byId("requestInterruptButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/interrupt/request", {
    method: "POST",
    body: JSON.stringify({
      actor_id: byId("interruptActorSelect").value,
      reason: byId("interruptReasonInput").value,
    }),
  });
  renderSnapshot(result.snapshot);
  showFeedback(result.message);
}));

byId("approveInterruptButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/interrupt/approve", {
    method: "POST",
    body: JSON.stringify({ actor_id: byId("interruptActorSelect").value }),
  });
  renderSnapshot(result.snapshot);
  showFeedback(result.message);
}));

byId("nominateButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/nominate-next", {
    method: "POST",
    body: JSON.stringify({
      actor_id: byId("nominateActorSelect").value,
      next_speaker: byId("nominateNextSelect").value,
      reason: byId("nominateReasonInput").value,
    }),
  });
  renderSnapshot(result.snapshot);
  showFeedback(result.message);
}));

byId("readNotebookButton").addEventListener("click", () => runAction(async () => {
  const params = new URLSearchParams(notebookParams());
  const result = await api(`/api/notebook?${params.toString()}`, { method: "GET", headers: {} });
  elements.notebookEditor.value = result.content || "";
  showFeedback(`已读取 ${result.owner_id}/${result.notebook_name}`);
}));

byId("searchNotebookButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/notebook/search", {
    method: "POST",
    body: JSON.stringify({ ...notebookParams(), query: byId("searchNotebookInput").value.trim() }),
  });
  elements.notebookEditor.value = result.content || "";
  showFeedback("Notebook 搜索完成。");
}));

byId("jumpNotebookButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/notebook/jump", {
    method: "POST",
    body: JSON.stringify({ ...notebookParams(), heading: byId("jumpHeadingInput").value.trim() }),
  });
  elements.notebookEditor.value = result.content || "";
  showFeedback("Notebook 标题读取完成。");
}));

byId("updateNotebookButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/notebook/update", {
    method: "POST",
    body: JSON.stringify({
      ...notebookParams(),
      content: elements.notebookEditor.value,
      mode: byId("notebookModeSelect").value,
      heading: byId("jumpHeadingInput").value.trim(),
    }),
  });
  renderSnapshot(result.snapshot);
  elements.notebookEditor.value = result.notebook?.content || elements.notebookEditor.value;
  showFeedback(result.message);
}));

byId("ruleQueryButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/rules/query", {
    method: "POST",
    body: JSON.stringify({
      query: byId("ruleQueryInput").value,
      doc_ids: byId("ruleDocIdsInput").value,
      top_k: 5,
    }),
  });
  elements.rulesOutput.textContent = result.message || "";
  showFeedback("规则查询完成。");
}));

byId("compileRulesButton").addEventListener("click", () => runAction(async () => {
  const result = await api("/api/rules/compile", {
    method: "POST",
    body: JSON.stringify({ doc_ids: byId("ruleDocIdsInput").value, output_path: "" }),
  });
  elements.rulesOutput.textContent = result.message || "";
  showFeedback("规则摘要生成完成。");
}));

renderSnapshot(bootstrap);
setInterval(() => {
  refreshSnapshot().catch(() => {});
}, 4000);