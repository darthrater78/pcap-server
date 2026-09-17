"use strict";

// Traffic Diagram (a force-directed graph of who talks to whom, with an
// opt-in playback of the actual packet order) and Sequence Diagram (a
// time-ordered swimlane per host, like Wireshark's own Flow Graph).
//
// No graphing library: the CSP (backend/main.py's script-src 'self') blocks
// any CDN script outright, and this frontend has never carried a third-party
// dependency, so both are hand-built in SVG (for anything that needs hover,
// click or drag) plus one <canvas> overlay (for the animated packet dots
// only, which need neither). Both reuse the existing statistics routes --
// /conversations for the static graph, /packets for anything per-packet --
// so there is nothing new on the backend.
//
// Protocol color is the dataviz skill's validated categorical palette
// (--diagram-cat-1/2/3 in style.css), not the app's existing --pkt-* row
// tints: those are tuned for a tint behind a text column and fail the
// identity-alone gates a node-link diagram and a swimlane both need (any two
// colors can end up adjacent). Capped at the first three slots -- the only
// ones that clear the stricter all-pairs check -- with everything else
// folded into one neutral --diagram-other, always paired with a label.

const TOPOLOGY_NODE_CAP = 200;
const PACKET_DIAGRAM_CAP = 5000;
const TOPOLOGY_PACKETS_PER_SECOND_AT_1X = 40;

function clamp(min, v, max) {
    return Math.max(min, Math.min(max, v));
}

const SVGNS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}) {
    const el = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
}

// Canvas's 2D context does not resolve CSS custom properties -- SVG
// attributes and inline styles do, so colorOf below keeps var(...) strings
// for everything except the one place (the animated dots) that needs a
// literal color.
function resolveColor(expr) {
    const m = /^var\((--[\w-]+)\)$/.exec(expr);
    if (!m) return expr;
    return getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim();
}

// Ranks the protocols actually present and assigns the three gate-safe
// categorical slots to the most common ones; everything past that shares one
// neutral "other" swatch rather than generating a fourth hue no CVD check
// covers.
function rankProtocols(packets) {
    const counts = new Map();
    for (const p of packets) counts.set(p.protocol, (counts.get(p.protocol) || 0) + 1);
    const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    const slots = ["var(--diagram-cat-1)", "var(--diagram-cat-2)", "var(--diagram-cat-3)"];
    const colorOf = new Map();
    ranked.forEach(([proto], i) => colorOf.set(proto, i < 3 ? slots[i] : "var(--diagram-other)"));
    return { ranked, colorOf };
}

function protocolColor(colorOf, proto) {
    return colorOf.get(proto) || "var(--diagram-other)";
}

function legendItem(color, label, count) {
    return `<span class="diagram-legend-item"><span class="diagram-legend-swatch" ` +
        `style="background:${color}"></span>${escHtml(label)} (${count.toLocaleString()})</span>`;
}

// Identity is never color-alone here: every swatch carries its own protocol
// name and count, both in the legend and (via <title>) on every mark.
function renderLegend(el, ranked, colorOf) {
    if (!ranked.length) {
        el.innerHTML = '<span class="diagram-legend-empty">No packets</span>';
        return;
    }
    const top = ranked.slice(0, 3);
    const otherCount = ranked.slice(3).reduce((s, [, c]) => s + c, 0);
    const items = top.map(([proto, count]) => legendItem(colorOf.get(proto), proto, count));
    if (otherCount) items.push(legendItem("var(--diagram-other)", "Other", otherCount));
    el.innerHTML = items.join("");
}

// Shared by both diagrams: the display filter's own packet count decides
// whether this renders at all. Truncating a diagram silently would just draw
// a wrong picture, so above the cap this returns overCap instead of a
// partial result.
async function fetchPacketsCapped(captureId, filter, cap = PACKET_DIAGRAM_CAP) {
    const pageSize = 1000;
    const params = (offset) => new URLSearchParams({ display_filter: filter, offset, limit: pageSize });
    const first = await api(`/api/captures/${captureId}/packets?${params(0)}`);
    if (first.total > cap) return { overCap: true, total: first.total };
    const packets = first.packets.slice();
    for (let offset = pageSize; offset < first.total; offset += pageSize) {
        const page = await api(`/api/captures/${captureId}/packets?${params(offset)}`);
        packets.push(...page.packets);
    }
    return { overCap: false, total: first.total, packets };
}

function showDiagramCapWarning(kind, total, cap, filter) {
    const box = $(`${kind}-cap-warning`);
    const what = kind === "topology" ? "hosts" : "packets";
    box.textContent = `${total.toLocaleString()} ${what} match ` +
        `${filter ? `"${filter}"` : "the whole capture"} -- above the ${cap.toLocaleString()} this diagram ` +
        "can render. Narrow the display filter, or open a saved view, and try again.";
    box.hidden = false;
    $(`${kind}-body`).hidden = true;
}

// --- Traffic Diagram (topology graph) ---------------------------------------

function buildTopologyNodes(endpoints) {
    const maxBytes = Math.max(1, ...endpoints.map((e) => e.bytes));
    return endpoints.map((e) => ({
        id: e.address,
        bytes: e.bytes,
        packets: e.packets,
        r: clamp(6, 6 + 22 * Math.sqrt(e.bytes / maxBytes), 28),
        x: 0,
        y: 0,
    }));
}

function buildTopologyEdges(convs) {
    const maxBytes = Math.max(1, ...convs.map((c) => c.bytes_a_to_b + c.bytes_b_to_a));
    return convs.map((c) => {
        const totalBytes = c.bytes_a_to_b + c.bytes_b_to_a;
        return {
            a: c.a,
            b: c.b,
            bytesAB: c.bytes_a_to_b,
            bytesBA: c.bytes_b_to_a,
            packetsAB: c.packets_a_to_b,
            packetsBA: c.packets_b_to_a,
            totalBytes,
            width: clamp(1, 1 + 6 * Math.sqrt(totalBytes / maxBytes), 7),
        };
    });
}

// A small hand-rolled force layout -- repulsion between every pair, a spring
// along each edge, a weak pull to center -- run to convergence once before
// the first paint rather than as a continuing simulation. Good enough at the
// node counts this ever sees (capped at TOPOLOGY_NODE_CAP) and means no
// per-frame layout cost competes with the playback animation later.
function runForceLayout(nodes, edges, width, height) {
    if (!nodes.length) return;
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const cx = width / 2;
    const cy = height / 2;
    const seedRadius = Math.min(width, height) * 0.35;
    nodes.forEach((n, i) => {
        const angle = (i / nodes.length) * Math.PI * 2;
        n.x = cx + Math.cos(angle) * seedRadius;
        n.y = cy + Math.sin(angle) * seedRadius;
    });
    const idealLen = Math.min(width, height) / Math.max(4, Math.sqrt(nodes.length));
    const iterations = nodes.length > 80 ? 80 : 150;

    for (let it = 0; it < iterations; it++) {
        const fx = new Map(nodes.map((n) => [n.id, 0]));
        const fy = new Map(nodes.map((n) => [n.id, 0]));

        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const a = nodes[i], b = nodes[j];
                let dx = a.x - b.x, dy = a.y - b.y;
                let dist2 = dx * dx + dy * dy;
                if (dist2 < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; dist2 = 0.01; }
                const dist = Math.sqrt(dist2);
                const force = (idealLen * idealLen) / dist2;
                const fxv = (dx / dist) * force, fyv = (dy / dist) * force;
                fx.set(a.id, fx.get(a.id) + fxv); fy.set(a.id, fy.get(a.id) + fyv);
                fx.set(b.id, fx.get(b.id) - fxv); fy.set(b.id, fy.get(b.id) - fyv);
            }
        }

        for (const e of edges) {
            const a = byId.get(e.a), b = byId.get(e.b);
            if (!a || !b) continue;
            const dx = b.x - a.x, dy = b.y - a.y;
            const dist = Math.max(0.1, Math.sqrt(dx * dx + dy * dy));
            const force = (dist - idealLen) * 0.02;
            const fxv = (dx / dist) * force, fyv = (dy / dist) * force;
            fx.set(a.id, fx.get(a.id) + fxv); fy.set(a.id, fy.get(a.id) + fyv);
            fx.set(b.id, fx.get(b.id) - fxv); fy.set(b.id, fy.get(b.id) - fyv);
        }

        const cooling = 1 - it / iterations;
        const maxStep = 40 * cooling + 1;
        for (const n of nodes) {
            const fxv = fx.get(n.id) + (cx - n.x) * 0.01;
            const fyv = fy.get(n.id) + (cy - n.y) * 0.01;
            n.x += clamp(-maxStep, fxv, maxStep);
            n.y += clamp(-maxStep, fyv, maxStep);
        }
    }

    fitNodesToBounds(nodes, width, height);
}

function fitNodesToBounds(nodes, width, height) {
    const pad = 40;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of nodes) {
        minX = Math.min(minX, n.x - n.r); maxX = Math.max(maxX, n.x + n.r);
        minY = Math.min(minY, n.y - n.r); maxY = Math.max(maxY, n.y + n.r);
    }
    const spanX = Math.max(1, maxX - minX), spanY = Math.max(1, maxY - minY);
    const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY, 1);
    for (const n of nodes) {
        n.x = pad + (n.x - minX) * scale;
        n.y = pad + (n.y - minY) * scale;
    }
}

function svgPoint(svg, ev) {
    const rect = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    return {
        x: ((ev.clientX - rect.left) / rect.width) * vb.width + vb.x,
        y: ((ev.clientY - rect.top) / rect.height) * vb.height + vb.y,
    };
}

function updateEdgePositions(edgeLayer, byId) {
    for (const line of edgeLayer.children) {
        const a = byId.get(line.dataset.a), b = byId.get(line.dataset.b);
        if (!a || !b) continue;
        line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
        line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    }
}

// Drag repositions just that node -- no re-simulation -- which is cheap and
// leaves the rest of a layout the user has already made sense of alone.
function makeDraggable(g, node, onMove) {
    let dragging = false;
    g.addEventListener("pointerdown", (ev) => {
        dragging = true;
        g.dataset.dragged = "";
        g.setPointerCapture(ev.pointerId);
    });
    g.addEventListener("pointermove", (ev) => {
        if (!dragging) return;
        const pt = svgPoint(g.ownerSVGElement, ev);
        node.x = pt.x; node.y = pt.y;
        g.setAttribute("transform", `translate(${node.x},${node.y})`);
        onMove();
    });
    const end = () => {
        if (!dragging) return;
        dragging = false;
        // Deferred so the click event that follows pointerup still sees it,
        // and a drag doesn't also fire the node's own click-to-filter.
        setTimeout(() => delete g.dataset.dragged, 0);
    };
    g.addEventListener("pointerup", end);
    g.addEventListener("pointercancel", end);
}

// Returns the edge layer, so the caller can keep it around for
// updateEdgePositions during playback and drag.
function renderTopologySVG(svg, nodes, byId, edges, onNodeClick, onEdgeClick) {
    svg.innerHTML = "";
    const width = svg.clientWidth || 800, height = svg.clientHeight || 500;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const edgeLayer = svgEl("g", { class: "diagram-edges" });
    const nodeLayer = svgEl("g", { class: "diagram-nodes" });
    svg.append(edgeLayer, nodeLayer);

    for (const e of edges) {
        const a = byId.get(e.a), b = byId.get(e.b);
        if (!a || !b) continue;
        const line = svgEl("line", {
            class: "diagram-edge", x1: a.x, y1: a.y, x2: b.x, y2: b.y, "stroke-width": e.width,
        });
        line.dataset.a = e.a; line.dataset.b = e.b;
        line.addEventListener("click", () => onEdgeClick(e));
        const title = svgEl("title");
        title.textContent = `${e.a} <-> ${e.b}: ${formatBytes(e.totalBytes)}, ` +
            `${(e.packetsAB + e.packetsBA).toLocaleString()} pkts`;
        line.append(title);
        edgeLayer.append(line);
    }

    for (const n of nodes) {
        const g = svgEl("g", { class: "diagram-node", transform: `translate(${n.x},${n.y})` });
        const circle = svgEl("circle", { r: n.r });
        const label = svgEl("text", { x: n.r + 4, y: 4 });
        label.textContent = n.id;
        const title = svgEl("title");
        title.textContent = `${n.id}: ${formatBytes(n.bytes)}, ${n.packets.toLocaleString()} pkts`;
        g.append(circle, label, title);
        g.addEventListener("click", () => { if (g.dataset.dragged === undefined) onNodeClick(n); });
        makeDraggable(g, n, () => updateEdgePositions(edgeLayer, byId));
        nodeLayer.append(g);
    }

    return edgeLayer;
}

function onTopologyNodeClick(n) {
    const field = addressField(n.id);
    if (!field) return;
    applyBuiltFilter(buildFieldFilter(field, n.id), "selected");
    $("topology-dialog").close();
}

function onTopologyEdgeClick(e) {
    const field = addressField(e.a);
    if (!field) return;
    const expr = `${buildFieldFilter(field, e.a)} && ${buildFieldFilter(field, e.b)}`;
    applyBuiltFilter(expr, "selected");
    $("topology-dialog").close();
}

let topologyState = null;
let topologyPlayback = null;

function resetTopologyPlayback() {
    if (topologyPlayback?.raf) cancelAnimationFrame(topologyPlayback.raf);
    topologyPlayback = null;
    $("btn-topology-play").disabled = true;
    $("btn-topology-play").textContent = "Play";
    $("topology-speed").disabled = true;
    $("topology-scrubber").disabled = true;
    $("topology-scrubber").value = 0;
    $("topology-playback-count").textContent = "";
}

async function openTopologyDialog() {
    if (!viewingCaptureId) return;
    const dialog = $("topology-dialog");
    const filter = $("display-filter").value.trim();
    $("topology-scope").textContent = filter ? `Packets matching: ${filter}` : "The whole capture";
    $("topology-cap-warning").hidden = true;
    $("topology-body").hidden = false;
    $("topology-legend").innerHTML =
        '<span class="diagram-legend-empty">Press Play to animate packet flow, colored by protocol</span>';
    resetTopologyPlayback();
    $("topology-svg").innerHTML = "";
    const canvas = $("topology-canvas");
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    dialog.showModal();
    try {
        const data = await api(
            `/api/captures/${viewingCaptureId}/conversations?${new URLSearchParams({ display_filter: filter })}`
        );
        if (data.endpoints.length > TOPOLOGY_NODE_CAP) {
            showDiagramCapWarning("topology", data.endpoints.length, TOPOLOGY_NODE_CAP, filter);
            return;
        }
        const nodes = buildTopologyNodes(data.endpoints);
        const edges = buildTopologyEdges(data.conversations);
        const svg = $("topology-svg");
        const width = svg.clientWidth || 800, height = svg.clientHeight || 500;
        canvas.width = width; canvas.height = height;
        runForceLayout(nodes, edges, width, height);
        const byId = new Map(nodes.map((n) => [n.id, n]));
        const edgeLayer = renderTopologySVG(svg, nodes, byId, edges, onTopologyNodeClick, onTopologyEdgeClick);
        topologyState = { captureId: viewingCaptureId, filter, nodes, edges, byId, edgeLayer };
        $("btn-topology-play").disabled = false;
    } catch (e) {
        $("topology-legend").innerHTML = `<span style="color:var(--danger)">${escHtml(e.message)}</span>`;
    }
}

async function onTopologyPlayClick() {
    if (!topologyState) return;
    if (!topologyPlayback) {
        $("btn-topology-play").disabled = true;
        $("btn-topology-play").textContent = "Loading…";
        let result;
        try {
            result = await fetchPacketsCapped(topologyState.captureId, topologyState.filter);
        } catch (e) {
            $("btn-topology-play").disabled = false;
            $("btn-topology-play").textContent = "Play";
            $("topology-legend").innerHTML = `<span style="color:var(--danger)">${escHtml(e.message)}</span>`;
            return;
        }
        $("btn-topology-play").disabled = false;
        if (result.overCap) {
            showDiagramCapWarning("topology", result.total, PACKET_DIAGRAM_CAP, topologyState.filter);
            return;
        }
        const { ranked, colorOf } = rankProtocols(result.packets);
        const resolvedColorOf = new Map([...colorOf].map(([proto, expr]) => [proto, resolveColor(expr)]));
        renderLegend($("topology-legend"), ranked, colorOf);
        topologyPlayback = { packets: result.packets, resolvedColorOf, playing: false, progress: 0, raf: null };
        $("topology-scrubber").max = String(result.packets.length);
        $("topology-scrubber").disabled = false;
        $("topology-speed").disabled = false;
    }
    topologyPlayback.playing = !topologyPlayback.playing;
    $("btn-topology-play").textContent = topologyPlayback.playing ? "Pause" : "Play";
    if (topologyPlayback.playing) startTopologyAnimation();
}

function drawTopologyFrame(ctx, canvas, playback) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const idx = Math.floor(playback.progress);
    const trailStart = Math.max(0, idx - 20);
    for (let i = trailStart; i <= idx && i < playback.packets.length; i++) {
        const p = playback.packets[i];
        const a = topologyState.byId.get(p.source), b = topologyState.byId.get(p.destination);
        if (!a || !b) continue;
        const frac = i === idx ? playback.progress - idx : 1;
        const x = a.x + (b.x - a.x) * frac, y = a.y + (b.y - a.y) * frac;
        ctx.globalAlpha = Math.max(0.08, 1 - (idx - i) / 20);
        ctx.fillStyle = playback.resolvedColorOf.get(p.protocol) || "#888";
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.globalAlpha = 1;
}

function updatePlaybackCount(playback) {
    const shown = Math.min(playback.packets.length, Math.floor(playback.progress) + 1);
    $("topology-playback-count").textContent = `${shown.toLocaleString()} / ${playback.packets.length.toLocaleString()}`;
}

function startTopologyAnimation() {
    const canvas = $("topology-canvas");
    const ctx = canvas.getContext("2d");
    let last = performance.now();

    function frame(now) {
        if (!topologyPlayback || !topologyPlayback.playing) return;
        const dt = (now - last) / 1000;
        last = now;
        const speed = parseFloat($("topology-speed").value) || 1;
        topologyPlayback.progress += dt * TOPOLOGY_PACKETS_PER_SECOND_AT_1X * speed;
        const total = topologyPlayback.packets.length;
        if (topologyPlayback.progress >= total) {
            topologyPlayback.progress = total;
            topologyPlayback.playing = false;
            $("btn-topology-play").textContent = "Play";
        }
        $("topology-scrubber").value = String(Math.floor(topologyPlayback.progress));
        updatePlaybackCount(topologyPlayback);
        drawTopologyFrame(ctx, canvas, topologyPlayback);
        if (topologyPlayback.playing) topologyPlayback.raf = requestAnimationFrame(frame);
    }
    topologyPlayback.raf = requestAnimationFrame(frame);
}

function onTopologyScrub() {
    if (!topologyPlayback) return;
    topologyPlayback.playing = false;
    $("btn-topology-play").textContent = "Play";
    topologyPlayback.progress = Number($("topology-scrubber").value);
    updatePlaybackCount(topologyPlayback);
    const canvas = $("topology-canvas");
    drawTopologyFrame(canvas.getContext("2d"), canvas, topologyPlayback);
}

// --- Sequence Diagram (swimlanes) -------------------------------------------

// Ordinal spacing, not real elapsed time: a burst of packets a millisecond
// apart is common and would otherwise collapse into an unreadable stack.
function buildSequenceLayout(packets, width) {
    const laneX = new Map();
    for (const p of packets) {
        if (!laneX.has(p.source)) laneX.set(p.source, 0);
        if (!laneX.has(p.destination)) laneX.set(p.destination, 0);
    }
    const hosts = [...laneX.keys()];
    const laneGap = hosts.length > 1 ? (width - 160) / (hosts.length - 1) : 0;
    hosts.forEach((h, i) => laneX.set(h, 80 + i * laneGap));
    const rowGap = 22, topPad = 44;
    return { hosts, laneX, rowGap, topPad, totalHeight: topPad + packets.length * rowGap + 30 };
}

function renderSequenceSVG(svg, packets, colorOf) {
    svg.innerHTML = "";
    const width = Math.max(svg.parentElement.clientWidth || 800, 400);
    const layout = buildSequenceLayout(packets, width);
    svg.setAttribute("viewBox", `0 0 ${width} ${layout.totalHeight}`);
    svg.style.width = "100%";
    svg.style.height = `${layout.totalHeight}px`;

    const defs = svgEl("defs");
    const marker = svgEl("marker", {
        id: "seq-arrowhead", markerWidth: 8, markerHeight: 8, refX: 7, refY: 4, orient: "auto",
    });
    marker.append(svgEl("path", { d: "M0,0 L8,4 L0,8 Z", fill: "context-stroke" }));
    defs.append(marker);

    const laneLayer = svgEl("g");
    const arrowLayer = svgEl("g");
    svg.append(defs, laneLayer, arrowLayer);

    for (const host of layout.hosts) {
        const x = layout.laneX.get(host);
        laneLayer.append(svgEl("line", {
            class: "seq-lane-line", x1: x, y1: layout.topPad - 12, x2: x, y2: layout.totalHeight - 10,
        }));
        const label = svgEl("text", { class: "seq-lane-label", x, y: layout.topPad - 20, "text-anchor": "middle" });
        label.textContent = host;
        laneLayer.append(label);
    }

    packets.forEach((p, i) => {
        const y = layout.topPad + i * layout.rowGap;
        const x1 = layout.laneX.get(p.source), x2 = layout.laneX.get(p.destination);
        const color = protocolColor(colorOf, p.protocol);
        const d = x1 === x2 ? `M${x1 - 12},${y} L${x1 + 12},${y}` : `M${x1},${y} L${x2},${y}`;
        const path = svgEl("path", {
            class: "seq-arrow", d, stroke: color, "stroke-width": 1.5, "marker-end": "url(#seq-arrowhead)",
        });
        path.dataset.frame = p.number;
        const title = svgEl("title");
        title.textContent = `#${p.number} ${p.protocol} ${p.source} → ${p.destination} ` +
            `(${formatBytes(p.length)}) ${p.info}`;
        path.append(title);
        arrowLayer.append(path);
    });
}

function initSequenceInteractions(svg) {
    svg.addEventListener("click", (e) => {
        const el = e.target.closest("[data-frame]");
        if (!el) return;
        selectPacket(Number(el.dataset.frame));
        $("sequence-dialog").close();
    });
}

async function openSequenceDialog() {
    if (!viewingCaptureId) return;
    const dialog = $("sequence-dialog");
    const filter = $("display-filter").value.trim();
    $("sequence-scope").textContent = filter ? `Packets matching: ${filter}` : "The whole capture";
    $("sequence-cap-warning").hidden = true;
    $("sequence-body").hidden = false;
    $("sequence-legend").innerHTML = '<span class="diagram-legend-empty"><span class="spinner"></span></span>';
    $("sequence-svg").innerHTML = "";
    dialog.showModal();
    try {
        const result = await fetchPacketsCapped(viewingCaptureId, filter);
        if (result.overCap) {
            showDiagramCapWarning("sequence", result.total, PACKET_DIAGRAM_CAP, filter);
            return;
        }
        if (!result.packets.length) {
            $("sequence-legend").innerHTML = '<span class="diagram-legend-empty">No packets</span>';
            return;
        }
        const { ranked, colorOf } = rankProtocols(result.packets);
        renderLegend($("sequence-legend"), ranked, colorOf);
        renderSequenceSVG($("sequence-svg"), result.packets, colorOf);
    } catch (e) {
        $("sequence-legend").innerHTML = `<span style="color:var(--danger)">${escHtml(e.message)}</span>`;
    }
}

// --- wiring -------------------------------------------------------------

function initDiagramDialogs() {
    for (const id of ["topology-dialog", "sequence-dialog"]) {
        const dialog = $(id);
        dialog?.addEventListener("click", (e) => {
            if (e.target.closest("[data-close-dialog]")) dialog.close();
        });
    }
    $("topology-dialog")?.addEventListener("close", () => {
        if (!topologyPlayback) return;
        topologyPlayback.playing = false;
        if (topologyPlayback.raf) cancelAnimationFrame(topologyPlayback.raf);
    });
    $("btn-topology")?.addEventListener("click", openTopologyDialog);
    $("btn-sequence")?.addEventListener("click", openSequenceDialog);
    $("btn-topology-play")?.addEventListener("click", onTopologyPlayClick);
    $("topology-scrubber")?.addEventListener("input", onTopologyScrub);
    const seqSvg = $("sequence-svg");
    if (seqSvg) initSequenceInteractions(seqSvg);
}

initDiagramDialogs();
