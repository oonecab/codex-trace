"use strict";
const ProcessViews = (() => {
  const get = (id) => document.getElementById(id),
    make = (tag, cls, text) => {
      const el = document.createElement(tag);
      if (cls) el.className = cls;
      if (text !== undefined) el.textContent = text;
      return el;
    };
  const phaseColors = {
    inspect: "#367760",
    change: "#9b702e",
    verify: "#4b7297",
    execute: "#60785d",
    tools: "#4b7297",
    delegate: "#74629c",
    context: "#8b7a43",
    wait: "#737e7a",
    statement: "#805f9a",
    other: "#77807c",
  };
  const graphLayout = {
    width: 1120,
    top: 68,
    row: 116,
    actionX: 44,
    actionWidth: 300,
    resultX: 402,
    resultWidth: 260,
    objectX: 786,
    objectWidth: 294,
    nodeHeight: 88,
  };
  const date = new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const tm = (ms) => (ms ? date.format(new Date(ms)) : "时间未记录");
  const key = (c) => c.turnId + "/" + c.eventId;
  const state = {
    data: null,
    analysis: null,
    cards: new Map(),
    events: new Map(),
    nodes: new Map(),
    mode: "process",
    turn: null,
    object: "",
    page: 0,
    edge: null,
    zoom: 1,
    expanded: new Set(),
    limits: new Map(),
    notes: new Set(),
    selected: null,
  };
  let callbacks = {};
  function configure(value) {
    callbacks = value;
    setView(state.mode);
  }
  function openCard(card) {
    const e = state.events.get(key(card));
    if (e) callbacks.openEvent(e);
  }
  const agentName = () => state.data?.session.sourceLabel || "Codex";
  const STATUS = { inProgress: "进行中", completed: "已结束", interrupted: "已中断", failed: "出错结束" };
  const statusLabel = (status) => STATUS[status] || "状态未记录";
  function badge(label, cls = "") {
    return make("span", "process-badge " + cls, label);
  }
  function setView(mode) {
    state.mode = mode;
    for (const name of ["process", "timeline", "graph"]) {
      get(name + "-view").hidden = name !== mode;
      get("view-" + name).setAttribute("aria-selected", String(name === mode));
      get("view-" + name).tabIndex = name === mode ? 0 : -1;
    }
    if (mode === "graph") renderGraph();
  }
  function select(eventKey) {
    state.selected = eventKey;
    document.querySelectorAll("[data-process-key]").forEach((el) => {
      const yes = el.dataset.processKey === eventKey;
      el.classList.toggle("selected", yes);
      if (el.tagName === "BUTTON") el.setAttribute("aria-pressed", String(yes));
    });
  }
  function render(data) {
    const switched = state.data?.session.id !== data.session.id;
    state.data = data;
    state.analysis = data.analysis;
    if (!state.analysis) {
      get("process-list").replaceChildren(make("p", "empty-state", "当前服务尚未提供过程分析，请重新启动服务。"));
      return;
    }
    state.cards = new Map(state.analysis.cards.map((c) => [c.id, c]));
    state.events = new Map(data.events.map((e) => [e.turnId + "/" + e.id, e]));
    state.nodes = new Map(state.analysis.graph.nodes.map((n) => [n.id, n]));
    if (switched) {
      state.turn = data.turns.at(-1)?.id || null;
      state.object = "";
      state.page = 0;
      state.edge = null;
      state.expanded.clear();
      state.limits.clear();
      state.notes.clear();
      state.selected = null;
    }
    if (!data.turns.some((t) => t.id === state.turn)) state.turn = data.turns.at(-1)?.id || null;
    get("graph-turn").replaceChildren(
      ...data.turns.map((t, i) => {
        const request = state.analysis.cards.find((c) => c.turnId === t.id && c.kind === "request");
        return new Option(`第 ${i + 1} 轮 · ${(request?.title || "没有请求文本").slice(0, 55)}`, t.id);
      }),
    );
    get("graph-turn").value = state.turn || "";
    const jumpValue = get("process-turn").value;
    get("process-turn").replaceChildren(
      new Option("跳转到轮次…", ""),
      ...data.turns.map((t, i) => new Option(`第 ${i + 1} 轮${t.status === "inProgress" ? " · 进行中" : ""}`, t.id)),
    );
    get("process-turn").value = switched ? "" : jumpValue;
    renderProcess();
    if (state.mode === "graph") renderGraph();
    select(state.selected);
  }
  function row(card) {
    const b = make("button", "process-step" + (card.attention ? " attention" : ""));
    b.type = "button";
    b.dataset.processKey = key(card);
    b.setAttribute("aria-pressed", String(state.selected === key(card)));
    b.style.setProperty("--phase-color", phaseColors[card.phase]);
    const head = make("div", "process-step-head");
    head.append(make("span", "step-kind", card.label), make("time", "", tm(card.timestamp)));
    if (card.attention) head.append(badge("需查看", "warn"));
    b.append(head, make("strong", "", card.title));
    if (card.hasResult) b.append(make("span", "step-result" + (card.attention ? " warn" : ""), card.resultLabel));
    else if (card.sourceKind === "statement")
      b.append(
        make(
          "span",
          "step-source",
          card.kind === "request" ? "用户请求" : agentName() + " 陈述 · " + card.statementHint,
        ),
      );
    if (card.preview && card.preview.replace(/\s+/g, " ").trim() !== card.title.trim())
      b.append(make("p", "step-preview", card.preview));
    b.addEventListener("click", () => openCard(card));
    return b;
  }
  function renderProcess() {
    if (!state.analysis) return;
    const scrolls = new Map(
      [...get("process-list").querySelectorAll(".process-turn")].map((el) => [
        el.dataset.turnId,
        el.querySelector(".phase-flow")?.scrollLeft || 0,
      ]),
    );
    const out = document.createDocumentFragment();
    state.analysis.turns.forEach((summary, index) => {
      const turn = state.data.turns.find((t) => t.id === summary.id) || {};
      const cards = state.analysis.cards.filter((c) => c.turnId === summary.id);
      const request = cards.find((c) => c.kind === "request");
      const article = make("article", "process-turn");
      article.dataset.turnId = summary.id;
      const header = make("div", "process-turn-heading"),
        number = make("span", "turn-number", String(index + 1).padStart(2, "0"));
      const title = make("div", "process-turn-title"),
        prompt = make("button");
      prompt.type = "button";
      prompt.append(make("h2", "", request?.title || "本轮没有保存请求文本"));
      if (request) prompt.addEventListener("click", () => openCard(request));
      title.append(prompt, make("small", "", tm(turn.startedAt) + " · " + statusLabel(turn.status)));
      const graph = make("button", "subtle-button", "查看关系 ↗");
      graph.type = "button";
      graph.addEventListener("click", () => showTurn(summary.id));
      header.append(number, title, graph);
      article.append(header, make("p", "process-summary", summary.summary));
      const chips = make("div", "process-facts");
      if (summary.testPassed) chips.append(badge(`${summary.testPassed} 次测试输出报告通过`, "good"));
      if (summary.testFailed) chips.append(badge(`${summary.testFailed} 次测试输出含失败`, "warn"));
      if (summary.testUnreported) chips.append(badge(`${summary.testUnreported} 次未识别测试汇总`));
      if (summary.attentionCount) chips.append(badge(`${summary.attentionCount} 条异常 / 非零退出`, "warn"));
      article.append(chips);
      const flow = make("div", "phase-flow");
      summary.stages.forEach((stage, i) => {
        if (i) flow.append(make("span", "phase-arrow", "→"));
        const b = make("button", "phase-chip");
        b.type = "button";
        b.style.setProperty("--phase-color", phaseColors[stage.phase]);
        b.setAttribute("aria-expanded", String(state.expanded.has(stage.id) || get("process-expand").checked));
        b.setAttribute(
          "aria-label",
          `第 ${index + 1} 轮，第 ${i + 1} 阶段：${stage.label}，${stage.cardIds.length} 步`,
        );
        b.append(make("span", "", stage.label), make("b", "", String(stage.cardIds.length)));
        b.addEventListener("click", () => {
          if (get("process-expand").checked) {
            get("process-expand").checked = false;
            state.expanded.clear();
          }
          state.expanded.has(stage.id) ? state.expanded.delete(stage.id) : state.expanded.add(stage.id);
          renderProcess();
          select(state.selected);
        });
        flow.append(b);
      });
      if (summary.stages.length) article.append(flow, make("p", "phase-hint", "点击阶段展开步骤 · 箭头仅表示记录顺序"));
      for (const stage of summary.stages) {
        if (!get("process-expand").checked && !state.expanded.has(stage.id)) continue;
        const section = make("section", "expanded-stage");
        section.append(make("h3", "", stage.label + " · " + stage.cardIds.length + " 步"));
        const limit = state.limits.get(stage.id) || 50;
        for (const id of stage.cardIds.slice(0, limit)) section.append(row(state.cards.get(id)));
        if (stage.cardIds.length > limit) {
          const more = make("button", "subtle-button", `继续显示剩余 ${stage.cardIds.length - limit} 步`);
          more.addEventListener("click", () => {
            state.limits.set(stage.id, limit + 100);
            renderProcess();
          });
          section.append(more);
        }
        article.append(section);
      }
      for (const series of summary.testSeries) {
        const box = make("div", "test-series");
        box.append(make("span", "series-label", `${series.label} · 同一命令执行 ${series.cardIds.length} 次`));
        series.cardIds.forEach((id, i) => {
          if (i) box.append(make("span", "series-arrow", "→"));
          const c = state.cards.get(id),
            b = make(
              "button",
              "series-attempt " + c.testOutcome,
              `${i + 1} · ${c.testOutcome === "passed" ? "报告通过" : c.testOutcome === "failed" ? "报告失败" : c.exitCode != null ? "退出 " + c.exitCode : "无测试汇总"}`,
            );
          b.title = c.resultLabel;
          b.addEventListener("click", () => openCard(c));
          box.append(b);
        });
        box.append(make("small", "", "按命令与目录匹配，未判断修复关系"));
        article.append(box);
      }
      const notes = cards.filter((c) => c.sourceKind === "statement" && c.readable && c.id !== request?.id);
      const foot = make("div", "process-turn-footer");
      if (notes.length) {
        const b = make(
          "button",
          "notes-toggle",
          `${state.notes.has(summary.id) ? "收起" : "查看"}说明与公开摘要 · ${notes.length}`,
        );
        b.setAttribute("aria-expanded", String(state.notes.has(summary.id)));
        b.addEventListener("click", () => {
          state.notes.has(summary.id) ? state.notes.delete(summary.id) : state.notes.add(summary.id);
          renderProcess();
          select(state.selected);
        });
        foot.append(b);
      }
      if (summary.unclassifiedCommands)
        foot.append(make("span", "", `${summary.unclassifiedCommands} 条命令未细分用途，可回查原文`));
      article.append(foot);
      if (state.notes.has(summary.id)) {
        const notesBox = make("div", "process-notes");
        notes.forEach((c) => notesBox.append(row(c)));
        article.append(notesBox);
      }
      out.append(article);
    });
    if (!state.analysis.turns.length) out.append(make("p", "empty-state", "尚无可整理的轮次。"));
    get("process-list").replaceChildren(out);
    get("process-list")
      .querySelectorAll(".process-turn")
      .forEach((el) => {
        const flow = el.querySelector(".phase-flow");
        if (flow) flow.scrollLeft = scrolls.get(el.dataset.turnId) || 0;
      });
  }
  function jumpProcess(id) {
    const article = [...get("process-list").children].find((el) => el.dataset.turnId === id);
    if (article) {
      get("process-turn").value = id;
      article.scrollIntoView({ block: "start", behavior: "instant" });
    }
  }
  function resetGraphScroll() {
    get("graph-canvas").scrollTop = 0;
    get("graph-canvas").scrollLeft = 0;
  }
  function applyGraphScale() {
    const scene = get("graph-canvas").querySelector("svg");
    if (scene) {
      scene.style.width = graphLayout.width * state.zoom + "px";
      scene.style.height = scene.viewBox.baseVal.height * state.zoom + "px";
    }
    get("graph-zoom-reset").textContent = Math.round(state.zoom * 100) + "%";
    get("graph-zoom-out").disabled = state.zoom <= 0.7;
    get("graph-zoom-in").disabled = state.zoom >= 1.3;
  }
  function setGraphZoom(value) {
    const canvas = get("graph-canvas"),
      previous = state.zoom;
    state.zoom = Math.round(Math.max(0.7, Math.min(1.3, value)) * 10) / 10;
    const ratio = state.zoom / previous,
      x = (canvas.scrollLeft + canvas.clientWidth / 2) * ratio,
      y = (canvas.scrollTop + canvas.clientHeight / 2) * ratio;
    applyGraphScale();
    canvas.scrollLeft = x - canvas.clientWidth / 2;
    canvas.scrollTop = y - canvas.clientHeight / 2;
  }
  function showTurn(id, object = "") {
    state.turn = id;
    state.object = object;
    state.page = 0;
    state.edge = null;
    get("graph-turn").value = id;
    setView("graph");
    resetGraphScroll();
    get("graph-view").scrollIntoView({ block: "start", behavior: "instant" });
  }
  const svgNS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs = {}, text) {
    const el = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function wrapped(text, max = 30, limit = 2) {
    const lines = [];
    let line = "",
      size = 0;
    for (const char of String(text || "")) {
      const w = char.charCodeAt(0) > 255 ? 2 : 1;
      if (size + w > max) {
        lines.push(line);
        line = "";
        size = 0;
        if (lines.length === limit) break;
      }
      line += char;
      size += w;
    }
    if (line && lines.length < limit) lines.push(line);
    if (lines.join("").length < String(text || "").length && lines.length)
      lines[lines.length - 1] = lines.at(-1).slice(0, -1) + "…";
    return lines;
  }
  function describeEdge(edge) {
    state.edge = edge.id;
    const block = get("graph-evidence");
    const basis = {
      record: "日志字段关联",
      order: "记录序号顺序，不表示完成先后或因果",
      rule: "规则匹配，不表示修复或因果",
    }[edge.basis];
    block.replaceChildren(make("strong", "", edge.label), make("span", "", basis));
    if (edge.interveningEdits?.length)
      block.append(make("span", "", `两次调用之间记录了 ${edge.interveningEdits.length} 次文件修改`));
    for (const proof of edge.evidence || []) block.append(make("small", "", proof.rule + " · " + proof.quote));
  }
  function graphClick(n) {
    if (n.cardId) {
      const card = state.cards.get(n.cardId);
      if (card) openCard(card);
    } else if (n.type === "agent") callbacks.openSession(n.sessionId);
    else if (n.type === "file") {
      state.object = n.id;
      state.page = 0;
      state.edge = null;
      renderGraph();
      resetGraphScroll();
    }
  }
  function renderGraph() {
    if (!state.analysis) return;
    const allEdges = state.analysis.graph.edges.filter((e) => e.turnId === state.turn),
      turnCards = state.analysis.cards.filter((c) => c.turnId === state.turn);
    const external = new Map();
    allEdges.forEach((e) => {
      const n = state.nodes.get(e.target);
      if (n && ["file", "agent"].includes(n.type)) external.set(n.id, n);
    });
    if (state.object && !external.has(state.object)) state.object = "";
    get("graph-object").replaceChildren(
      new Option("全部对象", ""),
      ...[...external.values()].map((n) => {
        const option = new Option(n.path || n.label, n.id);
        option.title = n.canonicalPath || n.path || n.label;
        return option;
      }),
    );
    get("graph-object").value = state.object;
    let pool = turnCards.filter(
      (c) => c.isOperation || (get("graph-statements").checked && c.readable && c.kind !== "request"),
    );
    if (!pool.length && !state.object)
      pool = turnCards.filter((c) => c.sourceKind === "statement" && c.readable && c.kind !== "request");
    if (state.object) {
      const ids = new Set(allEdges.filter((e) => e.target === state.object).map((e) => e.source));
      pool = pool.filter((c) => ids.has(c.id));
    }
    pool.sort((a, b) => a.ordinal - b.ordinal);
    const pageSize = 12,
      pages = Math.max(1, Math.ceil(pool.length / pageSize));
    state.page = Math.min(state.page, pages - 1);
    const shown = pool.slice(state.page * pageSize, (state.page + 1) * pageSize);
    get("graph-page").textContent = `${state.page + 1} / ${pages}`;
    get("graph-prev").disabled = state.page === 0;
    get("graph-next").disabled = state.page >= pages - 1;
    get("graph-count").textContent = `显示 ${shown.length} / ${pool.length} 个步骤 · 每页 ${pageSize} 步`;
    get("graph-evidence").replaceChildren(make("span", "", "点击节点回查记录，点击连线查看关联依据。"));
    const selectedEdge = allEdges.find((e) => e.id === state.edge);
    if (selectedEdge) describeEdge(selectedEdge);
    if (!shown.length) {
      get("graph-canvas").replaceChildren(make("p", "empty-state", "这一轮尚无匹配的可展示步骤。"));
      return;
    }
    const positions = new Map(),
      shownIds = new Set(shown.map((c) => c.id));
    const layout = graphLayout;
    shown.forEach((card, i) => {
      positions.set(card.id, {
        x: layout.actionX,
        y: layout.top + i * layout.row,
        w: layout.actionWidth,
        h: layout.nodeHeight,
        node: state.nodes.get(card.id),
        card,
      });
      const result = allEdges.find((e) => e.source === card.id && e.kind === "returns");
      if (result)
        positions.set(result.target, {
          x: layout.resultX,
          y: layout.top + i * layout.row,
          w: layout.resultWidth,
          h: layout.nodeHeight,
          node: state.nodes.get(result.target),
          card,
        });
    });
    let objectY = layout.top,
      objectCount = 0,
      omitted = 0;
    for (const edge of allEdges) {
      if (!shownIds.has(edge.source)) continue;
      const n = external.get(edge.target);
      if (!n || positions.has(n.id)) continue;
      if (objectCount >= 24) {
        omitted++;
        continue;
      }
      objectY = Math.max(objectY, positions.get(edge.source).y);
      positions.set(n.id, { x: layout.objectX, y: objectY, w: layout.objectWidth, h: 76, node: n });
      objectY += 94;
      objectCount++;
    }
    const height = Math.max(220, layout.top + shown.length * layout.row, objectY + 20);
    const scene = svg("svg", {
      viewBox: `0 0 ${layout.width} ${height}`,
      width: layout.width,
      height,
      role: "group",
      "aria-label": "动作、返回结果及关联对象",
    });
    const defs = svg("defs"),
      marker = svg("marker", {
        id: "process-arrow",
        markerWidth: 6,
        markerHeight: 6,
        refX: 5,
        refY: 3,
        orient: "auto",
      });
    marker.append(svg("path", { d: "M0,0 L6,3 L0,6", class: "graph-arrow" }));
    defs.append(marker);
    scene.append(defs);
    for (const [x, w] of [
      [layout.actionX, layout.actionWidth],
      [layout.resultX, layout.resultWidth],
      [layout.objectX, layout.objectWidth],
    ])
      scene.append(svg("rect", { x: x - 14, y: 12, width: w + 28, height: height - 24, rx: 16, class: "graph-lane" }));
    scene.append(
      svg("text", { x: layout.actionX + 2, y: 40, class: "graph-column" }, "记录的动作"),
      svg("text", { x: layout.resultX + 2, y: 40, class: "graph-column" }, "执行返回 / 输出报告"),
      svg("text", { x: layout.objectX + 2, y: 40, class: "graph-column" }, "关联文件 / 子代理"),
    );
    for (const edge of allEdges) {
      const a = positions.get(edge.source),
        b = positions.get(edge.target);
      if (!a || !b || edge.kind === "contains") continue;
      const order = ["sequence", "same_test_command"].includes(edge.kind);
      let d;
      if (order) {
        const x = edge.kind === "sequence" ? 26 : 12;
        d = `M${a.x},${a.y + a.h / 2} C${x},${a.y + a.h / 2} ${x},${b.y + b.h / 2} ${b.x},${b.y + b.h / 2}`;
      } else if (external.has(edge.target)) {
        // Route object references below the result box, so no result appears to point at a file.
        const x1 = a.x + a.w,
          y1 = a.y + a.h - 16,
          viaY = a.y + a.h + 13,
          y2 = b.y + b.h / 2;
        d = `M${x1},${y1} L${x1 + 18},${y1} L${x1 + 18},${viaY} L${layout.resultX + layout.resultWidth + 42},${viaY} L${layout.objectX - 24},${y2} L${b.x},${y2}`;
      } else {
        const x1 = a.x + a.w,
          y1 = a.y + a.h / 2,
          x2 = b.x,
          y2 = b.y + b.h / 2;
        d = `M${x1},${y1} C${x1 + 35},${y1} ${x2 - 35},${y2} ${x2},${y2}`;
      }
      const line = svg("g", { class: "graph-connection", tabindex: 0, role: "button", "aria-label": edge.label });
      line.append(
        svg("path", { d, class: "graph-edge-hit" }),
        svg("path", { d, class: "graph-edge " + edge.basis, "marker-end": "url(#process-arrow)" }),
        svg("title", {}, edge.label),
      );
      const act = () => describeEdge(edge);
      line.addEventListener("click", act);
      line.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          act();
        }
      });
      scene.append(line);
    }
    for (const p of positions.values()) {
      const n = p.node;
      if (!n) continue;
      const isResult = n.type === "result",
        c = p.card,
        color =
          n.type === "file"
            ? "#9b702e"
            : n.type === "agent"
              ? "#74629c"
              : isResult && n.attention
                ? "#a06035"
                : phaseColors[c?.phase] || "#60785d";
      const group = svg("g", {
        transform: `translate(${p.x},${p.y})`,
        class: "graph-node " + n.type + (isResult && n.attention ? " attention" : ""),
        tabindex: 0,
        role: "button",
        "aria-label": n.label,
      });
      if (c) group.dataset.processKey = key(c);
      group.append(
        svg("rect", { width: p.w, height: p.h, rx: 12 }),
        svg("circle", { cx: 18, cy: 22, r: 4, fill: color }),
      );
      group.append(
        svg(
          "text",
          { x: 30, y: 26, class: "graph-node-type", fill: color },
          isResult ? "返回记录" : n.type === "file" ? "文件" : n.type === "agent" ? "子代理" : c?.label || "说明",
        ),
      );
      const label = isResult
        ? n.label
        : n.type === "file"
          ? n.label
          : n.type === "agent"
            ? n.sessionId.slice(0, 22)
            : c?.title || n.label;
      wrapped(label, Math.floor((p.w - 34) / 7.2), 2).forEach((line, i) =>
        group.append(svg("text", { x: 16, y: 48 + i * 20, class: "graph-node-text" }, line)),
      );
      group.append(svg("title", {}, n.path || n.label));
      const action = () => graphClick(n);
      group.addEventListener("click", action);
      group.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          action();
        }
      });
      scene.append(group);
    }
    get("graph-canvas").replaceChildren(scene);
    applyGraphScale();
    if (omitted) get("graph-count").textContent += ` · 部分对象已收起，完整路径见步骤详情`;
    select(state.selected);
  }
  function insight(detail) {
    const card = state.analysis?.cards.find((c) => c.eventId === detail.id && c.turnId === detail.turnId);
    if (!card) return null;
    const block = make("section", "detail-block rule-insight");
    block.append(make("h4", "", card.sourceKind === "statement" ? "记录中的陈述" : "过程卡片"));
    const labels = make("div", "insight-badges");
    labels.append(
      badge(card.label),
      badge(
        card.sourceKind === "statement" ? (card.kind === "request" ? "用户请求" : agentName() + " 陈述") : "日志事实",
      ),
    );
    if (card.statementHint && card.kind !== "request") labels.append(badge(card.statementHint));
    block.append(labels);
    if (card.hasResult) block.append(make("p", "insight-result", card.resultLabel));
    for (const report of card.testReports) block.append(make("pre", "report-quote", report.quote));
    if (card.sourceKind === "statement")
      block.append(make("p", "insight-note", "陈述按原文展示；措辞标签由固定规则识别，不代表结果已验证。"));
    const related = state.analysis.graph.edges.filter((e) => e.source === card.id || e.target === card.id);
    for (const edge of related) {
      if (["reads", "writes", "write_attempt", "targets"].includes(edge.kind) && edge.source === card.id) {
        const n = state.nodes.get(edge.target),
          b = make("button", "related-link", edge.label + " · " + n.path);
        b.title = n.canonicalPath || n.path;
        b.addEventListener("click", () => {
          callbacks.closeDetail();
          showTurn(card.turnId, n.id);
        });
        block.append(b);
      } else if (edge.kind === "same_test_command") {
        const earlier = edge.target === card.id,
          other = state.cards.get(earlier ? edge.source : edge.target);
        const b = make(
          "button",
          "related-link",
          (earlier ? "前一次" : "后一次") + "相同测试命令 · " + tm(other.timestamp),
        );
        b.addEventListener("click", () => openCard(other));
        block.append(
          b,
          make(
            "small",
            "insight-note",
            `同轮字面命令与目录匹配；中间 ${edge.interveningEdits?.length || 0} 次文件修改，未判断因果。`,
          ),
        );
      }
    }
    const rules = make("details", "rule-evidence"),
      summary = make("summary", "", "查看识别依据");
    rules.append(summary);
    for (const proof of card.evidence) {
      const item = make("div", "proof");
      item.append(make("strong", "", proof.rule), make("small", "", proof.field), make("pre", "", proof.quote));
      rules.append(item);
    }
    block.append(rules);
    return block;
  }
  document.querySelectorAll("[data-view]").forEach((el) => {
    el.addEventListener("click", () => setView(el.dataset.view));
    el.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...document.querySelectorAll("[data-view]")],
        next = tabs[(tabs.indexOf(el) + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      setView(next.dataset.view);
      next.focus();
    });
  });
  get("process-expand").addEventListener("change", () => {
    renderProcess();
    select(state.selected);
  });
  get("process-turn").addEventListener("change", (event) => jumpProcess(event.target.value));
  get("process-latest").addEventListener("click", () => jumpProcess(state.data?.turns.at(-1)?.id));
  get("graph-turn").addEventListener("change", (event) => {
    state.turn = event.target.value;
    state.object = "";
    state.page = 0;
    state.edge = null;
    renderGraph();
    resetGraphScroll();
  });
  get("graph-object").addEventListener("change", (event) => {
    state.object = event.target.value;
    state.page = 0;
    state.edge = null;
    renderGraph();
    resetGraphScroll();
  });
  get("graph-statements").addEventListener("change", () => {
    state.page = 0;
    state.edge = null;
    renderGraph();
    resetGraphScroll();
  });
  get("graph-prev").addEventListener("click", () => {
    state.page = Math.max(0, state.page - 1);
    state.edge = null;
    renderGraph();
    get("graph-canvas").scrollTop = 0;
  });
  get("graph-next").addEventListener("click", () => {
    state.page++;
    state.edge = null;
    renderGraph();
    get("graph-canvas").scrollTop = 0;
  });
  get("graph-zoom-out").addEventListener("click", () => setGraphZoom(state.zoom - 0.1));
  get("graph-zoom-in").addEventListener("click", () => setGraphZoom(state.zoom + 0.1));
  get("graph-zoom-reset").addEventListener("click", () => setGraphZoom(1));
  return { configure, render, select, insight, statusLabel };
})();
