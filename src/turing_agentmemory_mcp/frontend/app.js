const state = {
  payload: null,
  activeTypes: new Set(),
  selectedNodeId: null,
  filteredNodeIds: new Set(),
};

const typeColors = {
  service: "#52d6b5",
  store: "#f0b84a",
  provider: "#9c8cff",
  memory: "#6fd08f",
  document: "#7fc7ff",
  benchmark: "#e87461",
  operation: "#f3f0e8",
};

const queryPresets = {
  memory:
    "MATCH {type: Memory, as: m}.out('PERSISTS'){as: store, where: (store.label = 'ArcadeDB')} RETURN m, store LIMIT 25",
  docs: "MATCH (d:Document)-[r]->(chunk) RETURN d,r,chunk LIMIT 25",
  bench: "MATCH (b:Benchmark)-[r:MEASURES]->(op) RETURN b,r,op ORDER BY op.p95_ms DESC",
};

const qs = (selector) => document.querySelector(selector);

function formatMs(value) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) return "0 ms";
  if (numeric >= 1000) return `${(numeric / 1000).toFixed(2)} s`;
  return `${numeric.toFixed(1)} ms`;
}

function formatPct(value) {
  const numeric = Number(value || 0);
  return `${(numeric * 100).toFixed(1)}%`;
}

function setText(selector, value) {
  const node = qs(selector);
  if (node) node.textContent = value;
}

async function loadPayload() {
  const response = await fetch("/api/graph/sample", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  state.payload = await response.json();
  state.activeTypes = new Set(state.payload.graph.nodes.map((node) => node.type));
  state.filteredNodeIds = new Set(state.payload.graph.nodes.map((node) => node.id));
  renderAll();
}

function renderAll() {
  renderMetrics();
  renderFilters();
  runQuery();
  renderTable();
}

function renderMetrics() {
  const benchmark = state.payload.benchmark;
  const summary = benchmark.summary;
  setText("#metric-artifact", benchmark.name || "none");
  setText("#metric-ops", String(summary.operation_count));
  setText("#metric-success", formatPct(summary.success_rate));
  setText("#metric-p50", formatMs(summary.best_p50_ms));
  setText("#metric-p95", formatMs(summary.slowest_p95_ms));
  setText("#field-status", summary.required_fields_ok ? "fields complete" : "fields incomplete");
}

function renderFilters() {
  const mount = qs("#type-filters");
  const types = [...new Set(state.payload.graph.nodes.map((node) => node.type))].sort();
  mount.innerHTML = "";
  for (const type of types) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = type;
    button.className = state.activeTypes.has(type) ? "active" : "";
    button.addEventListener("click", () => {
      if (state.activeTypes.has(type)) {
        state.activeTypes.delete(type);
      } else {
        state.activeTypes.add(type);
      }
      renderFilters();
      renderGraph();
    });
    mount.append(button);
  }
}

function runQuery() {
  const start = performance.now();
  const query = qs("#query-input").value.toLowerCase();
  const nodes = state.payload.graph.nodes;
  const edges = state.payload.graph.edges;
  const terms = query
    .replace(/[^a-z0-9_ ]/g, " ")
    .split(/\s+/)
    .filter((term) => term.length > 3 && !["match", "return", "limit", "order"].includes(term));

  const matched = new Set();
  for (const node of nodes) {
    const haystack = JSON.stringify(node).toLowerCase();
    if (!terms.length || terms.some((term) => haystack.includes(term))) {
      matched.add(node.id);
    }
  }

  const related = new Set(matched);
  for (const edge of edges) {
    if (matched.has(edge.source) || matched.has(edge.target)) {
      related.add(edge.source);
      related.add(edge.target);
    }
  }

  state.filteredNodeIds = related;
  const visibleEdges = edges.filter((edge) => related.has(edge.source) && related.has(edge.target));
  const elapsed = performance.now() - start;
  setText("#query-status", `Executed in ${elapsed.toFixed(1)} ms`);
  setText("#query-counts", `${related.size} nodes, ${visibleEdges.length} relationships`);
  renderGraph();
}

function renderGraph() {
  const svg = qs("#graph-canvas");
  const nodes = state.payload.graph.nodes;
  const edges = state.payload.graph.edges;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  svg.innerHTML = "";

  for (const edge of edges) {
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    if (!source || !target) continue;
    const active = isNodeVisible(source) && isNodeVisible(target);

    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", source.x);
    line.setAttribute("y1", source.y);
    line.setAttribute("x2", target.x);
    line.setAttribute("y2", target.y);
    line.setAttribute("class", `edge${active ? "" : " dimmed"}`);
    svg.append(line);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", (source.x + target.x) / 2);
    label.setAttribute("y", (source.y + target.y) / 2 - 7);
    label.setAttribute("class", `edge-label${active ? "" : " dimmed"}`);
    label.textContent = edge.label;
    svg.append(label);
  }

  for (const node of nodes) {
    const active = isNodeVisible(node);
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", `node${active ? "" : " dimmed"}${state.selectedNodeId === node.id ? " selected" : ""}`);
    group.setAttribute("transform", `translate(${node.x} ${node.y})`);
    group.addEventListener("click", () => selectNode(node.id));

    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("r", node.type === "operation" ? 28 : 40);
    circle.setAttribute("fill", typeColors[node.type] || "#f3f0e8");
    group.append(circle);

    const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
    title.setAttribute("text-anchor", "middle");
    title.setAttribute("y", node.type === "operation" ? 50 : 62);
    title.textContent = shorten(node.label, 22);
    group.append(title);

    const subtitle = document.createElementNS("http://www.w3.org/2000/svg", "text");
    subtitle.setAttribute("text-anchor", "middle");
    subtitle.setAttribute("y", node.type === "operation" ? 67 : 79);
    subtitle.setAttribute("class", "subtext");
    subtitle.textContent = node.type;
    group.append(subtitle);

    svg.append(group);
  }
}

function isNodeVisible(node) {
  return state.activeTypes.has(node.type) && state.filteredNodeIds.has(node.id);
}

function shorten(value, max) {
  const text = String(value || "");
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

function selectNode(id) {
  state.selectedNodeId = id;
  const node = state.payload.graph.nodes.find((item) => item.id === id);
  const inspector = qs("#inspector");
  inspector.innerHTML = "";

  const title = document.createElement("h2");
  title.textContent = node.label;
  inspector.append(title);

  const dl = document.createElement("dl");
  for (const [key, rawValue] of Object.entries(node)) {
    if (["x", "y", "id"].includes(key) || rawValue === undefined || rawValue === null) continue;
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = key;
    dd.textContent = key.endsWith("_ms") ? formatMs(rawValue) : String(rawValue);
    dl.append(dt, dd);
  }
  inspector.append(dl);
  renderGraph();
}

function renderTable() {
  const body = qs("#benchmark-table");
  const rows = state.payload.benchmark.rows || [];
  body.innerHTML = "";
  for (const row of rows) {
    const tr = document.createElement("tr");
    const cells = [
      row.operation,
      row.count,
      formatMs(row.p50_ms),
      formatMs(row.p95_ms),
      formatMs(row.p99_ms),
      formatPct(row.success_rate),
    ];
    for (const cell of cells) {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.append(td);
    }
    body.append(tr);
  }
}

function switchTab(view) {
  qs("#graph-view").classList.toggle("hidden", view !== "graph");
  qs("#table-view").classList.toggle("hidden", view !== "table");
  qs("#tab-graph").classList.toggle("active", view === "graph");
  qs("#tab-table").classList.toggle("active", view === "table");
}

function bindEvents() {
  qs("#run-query").addEventListener("click", runQuery);
  qs("#query-input").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      runQuery();
    }
  });
  qs("#query-memory").addEventListener("click", () => {
    qs("#query-input").value = queryPresets.memory;
    runQuery();
  });
  qs("#query-docs").addEventListener("click", () => {
    qs("#query-input").value = queryPresets.docs;
    runQuery();
  });
  qs("#query-bench").addEventListener("click", () => {
    qs("#query-input").value = queryPresets.bench;
    runQuery();
  });
  qs("#tab-graph").addEventListener("click", () => switchTab("graph"));
  qs("#tab-table").addEventListener("click", () => switchTab("table"));
}

bindEvents();
loadPayload().catch((error) => {
  setText("#query-status", `Load failed: ${error.message}`);
});
