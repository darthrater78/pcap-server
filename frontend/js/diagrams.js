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
// Protocol identity is the dataviz skill's validated categorical palette
// (--diagram-cat-1/2/3 in style.css), not the app's existing --pkt-* row
// tints: those are tuned for a tint behind a text column and fail the
// identity-alone gates a node-link diagram and a swimlane both need (any two
// colors can end up adjacent).
//
// It used to stop at three protocols, one hue each, with everything past the
// third folded into a neutral grey. Eight are wanted, and eight hues is not
// available: run the skill's validator over its whole eight-slot palette on
// the all-pairs list this diagram needs and both modes hard-FAIL (light CVD
// 3.2, normal-vision 7.1; dark CVD 1.6, normal-vision 7.1), and a
// normal-vision pair below 15 is a gate no amount of secondary encoding
// excuses. Enumerating every subset of those eight hues, FOUR is the most that
// clears all-pairs in both modes, and only two orderings manage it, both
// sitting in the 6-8 CVD warn band. The three already here clear at 9.2 light
// / 9.4 dark, comfortably past the target.
//
// So the eight slots come from composite encoding, which is what the skill
// prescribes past the color ceiling -- three validated hues by three shapes.
// Any two slots differ in hue (>= 9.2 apart, measured) or share a hue and
// differ in shape, so no pair rests on a color distinction that was never
// verified. Zero hex values change: a capture whose traffic is three protocols
// looks exactly as it did.
//
// The shape channel is spent where each diagram has one to spend: the topology
// draws marks, so it varies the mark's outline; the sequence diagram draws
// lines, which have no shape, so it varies the stroke dash. Both are driven by
// the same slot index, and the legend swatch draws the real mark rather than a
// colored square, so what identifies a protocol on screen is what identifies
// it in the legend.
//
// Light-mode aqua is 2.82:1 on the white canvas, under the 3:1 bar. The
// skill's relief rule covers it and is satisfied twice over: every legend
// entry is labelled with its protocol name and count, and every mark carries a
// <title>. The Conversations dialog is the table view of the same data.
const PROTOCOL_SLOT_CAP = 8;

// The Traffic Diagram draws marks, and marks have more shapes to spend than
// the Sequence Diagram's lines have dashes -- so it goes further: the same
// three validated hues across five shapes, fifteen slots, every one of them
// colored. Measured, not assumed (dataviz validator, both modes, every pair):
// adding a fourth hue from the reference palette puts at least one pair
// below the normal-vision floor or into the CVD warn band, and at most four
// hues can share a screen at all. Shape, not a new hue, is what scales.
const TOPOLOGY_SLOT_CAP = 15;

// Hue cycles fastest so the first three slots are one hue each, exactly as
// before. The grid holds nine combinations; the cap of eight is a legend-width
// choice, not a color-safety limit, which is why one combination goes unused.
// Order is fixed and never cycled -- a ninth protocol folds into "Other".
const PROTOCOL_SLOTS = [
    { color: "var(--diagram-cat-1)", shape: "circle", dash: "" },
    { color: "var(--diagram-cat-2)", shape: "square", dash: "6 3" },
    { color: "var(--diagram-cat-3)", shape: "diamond", dash: "1 3" },
    { color: "var(--diagram-cat-1)", shape: "square", dash: "6 3" },
    { color: "var(--diagram-cat-2)", shape: "diamond", dash: "1 3" },
    { color: "var(--diagram-cat-3)", shape: "circle", dash: "" },
    { color: "var(--diagram-cat-1)", shape: "diamond", dash: "1 3" },
    { color: "var(--diagram-cat-2)", shape: "circle", dash: "" },
    // Traffic Diagram only (TOPOLOGY_SLOT_CAP) from here: the sequence
    // legend stops at eight, so these never need a dash of their own.
    { color: "var(--diagram-cat-3)", shape: "square", dash: "" },
    { color: "var(--diagram-cat-1)", shape: "triangle", dash: "" },
    { color: "var(--diagram-cat-2)", shape: "ring", dash: "" },
    { color: "var(--diagram-cat-3)", shape: "triangle", dash: "" },
    { color: "var(--diagram-cat-1)", shape: "ring", dash: "" },
    { color: "var(--diagram-cat-2)", shape: "triangle", dash: "" },
    { color: "var(--diagram-cat-3)", shape: "ring", dash: "" },
];

// Everything past the cap. A neutral, and the one slot whose label is not a
// protocol name -- so it never claims an identity it cannot distinguish.
const OTHER_SLOT = { color: "var(--diagram-other)", shape: "circle", dash: "2 2" };

const TOPOLOGY_NODE_CAP = 200;
const SEQUENCE_LANE_CAP = 40;
// Each diagram's packet cap, switchable on the Capture tab
// (diagramPacketLimit). The Sequence Diagram draws a row per packet, and
// past a few thousand rows it is no longer something anyone reads. The
// Traffic Diagram's matches max_capture_packets' default; the server clamps
// either to that setting as it stands.
const PACKET_DIAGRAM_CAP = 5000;
const TOPOLOGY_PACKET_CAP = 100000;
const TOPOLOGY_PACKETS_PER_SECOND_AT_1X = 40;
// ...until a play at 1x would outlast this many seconds; past that the rate
// grows with the capture, so 100,000 packets play in the same two minutes as
// 5,000 rather than in forty.
const TOPOLOGY_PLAY_SECONDS_AT_1X = 120;
// How many times a link can be crossed before its "heat" (opacity/width
// boost during playback) stops climbing -- a link that carries most of the
// capture should read as busy, not turn into a solid bar that drowns out
// everything around it.
const EDGE_HEAT_CAP = 12;

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
// attributes and inline styles do, so PROTOCOL_SLOTS below keeps var(...)
// strings and only the canvas (the animated packet marks, and the backdrop
// ring around them) resolves them to literal colors.
function resolveColor(expr) {
    const m = /^var\((--[\w-]+)\)$/.exec(expr);
    if (!m) return expr;
    return getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim();
}

// Ranks the protocols actually present and hands each of the most common ones
// a slot from the fixed table above; everything past the cap shares the neutral
// "other" slot rather than generating a hue no CVD check covers.
function rankProtocols(packets, cap = PROTOCOL_SLOT_CAP) {
    const counts = new Map();
    for (const p of packets) counts.set(p.protocol, (counts.get(p.protocol) || 0) + 1);
    const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    const slotOf = new Map();
    ranked.forEach(([proto], i) => {
        slotOf.set(proto, i < cap ? PROTOCOL_SLOTS[i] : OTHER_SLOT);
    });
    return { ranked, slotOf };
}

function protocolSlot(slotOf, proto) {
    return slotOf.get(proto) || OTHER_SLOT;
}

// The legend swatch is the mark, drawn: the slot's dash on a short line and
// the slot's shape on top of it. A colored square would tell a reader which
// hue a protocol has and leave them to guess which of the same-hue shapes on
// the canvas is theirs.
function slotSwatch(slot) {
    const shape = {
        circle: '<circle cx="9" cy="7" r="4"></circle>',
        square: '<rect x="5" y="3" width="8" height="8"></rect>',
        diamond: '<path d="M9,2 L14,7 L9,12 L4,7 Z"></path>',
        triangle: '<path d="M9,2 L14,11 L4,11 Z"></path>',
        ring: '<circle cx="9" cy="7" r="3.5" fill="none" stroke-width="2"></circle>',
    }[slot.shape];
    return `<svg class="diagram-legend-swatch" width="18" height="14" viewBox="0 0 18 14" ` +
        `aria-hidden="true" fill="${slot.color}" stroke="${slot.color}">` +
        `<line x1="0" y1="7" x2="18" y2="7" stroke-width="1.5"` +
        (slot.dash ? ` stroke-dasharray="${slot.dash}"` : "") + `></line>${shape}</svg>`;
}

function legendItem(slot, label, count) {
    return `<span class="diagram-legend-item">${slotSwatch(slot)}` +
        `${escHtml(label)} (${count.toLocaleString()})</span>`;
}

// Identity is never color-alone here: every entry carries its own protocol
// name and count beside a swatch that draws the actual mark, and every mark on
// the canvas repeats the name via <title>.
function renderLegend(el, ranked, slotOf) {
    if (!ranked.length) {
        el.innerHTML = '<span class="diagram-legend-empty">No packets</span>';
        return;
    }
    const top = ranked.slice(0, PROTOCOL_SLOT_CAP);
    const otherCount = ranked.slice(PROTOCOL_SLOT_CAP).reduce((s, [, c]) => s + c, 0);
    const items = top.map(([proto, count]) => legendItem(protocolSlot(slotOf, proto), proto, count));
    if (otherCount) items.push(legendItem(OTHER_SLOT, "Other", otherCount));
    el.innerHTML = items.join("");
}

// --- Problems: resets, retransmissions, fragments ... ------------------------
//
// Read off each packet's Info column with the same patterns the packet list
// colors its "Problem" and "Reset" rows by (app.js PACKET_RULES), split into
// the kinds worth telling apart. Each carries the display filter that selects
// the same packets in the viewer, which is what clicking one applies.
const PROBLEM_KINDS = [
    { key: "reset", label: "Resets", test: /\brst\b/i, filter: "tcp.flags.reset == 1" },
    {
        key: "retrans", label: "Retransmissions / lost", test: /retransmission|out-of-order|previous segment|dup ack/i,
        filter: "tcp.analysis.retransmission || tcp.analysis.fast_retransmission || " +
            "tcp.analysis.out_of_order || tcp.analysis.lost_segment || tcp.analysis.duplicate_ack",
    },
    {
        key: "window", label: "Window problems", test: /zerowindow|window full/i,
        filter: "tcp.analysis.zero_window || tcp.analysis.window_full",
    },
    { key: "frag", label: "IP fragments", test: /fragmented ip protocol|reassembled in/i, filter: "ip.flags.mf == 1 || ip.frag_offset > 0" },
    {
        key: "icmp", label: "ICMP errors", test: /unreachable|time exceeded/i,
        filter: "icmp.type == 3 || icmp.type == 11 || icmpv6.type == 1 || icmpv6.type == 3",
    },
    { key: "malformed", label: "Malformed", test: /malformed|bad checksum/i, filter: "_ws.malformed" },
];

// Chip key for "only problem packets"; NUL-prefixed so no protocol can match.
const PROBLEMS_KEY = "\u0000problems";

// Packet -> its problem kind, computed once when the packets arrive.
const PROBLEM_OF = new WeakMap();

function classifyProblems(packets) {
    const counts = new Map();
    for (const p of packets) {
        const info = p.info || "";
        const kind = PROBLEM_KINDS.find((k) => k.test.test(info));
        if (!kind) continue;
        PROBLEM_OF.set(p, kind);
        counts.set(kind.key, (counts.get(kind.key) || 0) + 1);
    }
    return counts;
}

function linkKey(a, b) {
    return a <= b ? `${a}|${b}` : `${b}|${a}`;
}

// The Traffic Diagram's legend is also its protocol picker, the way the
// viewer's saved-view tabs pick a filter: "All" plus one chip per protocol,
// each a toggle, any number at once. A pick applies to the NEXT play -- it
// rewinds rather than splicing packets out of one already under way, so a
// play always shows one consistent set from its first packet to its last.
//
// Every protocol in the capture gets a chip of its own; unlike the Sequence
// Diagram's legend nothing folds into "Other". The first TOPOLOGY_SLOT_CAP
// each have a colored mark of their own; a capture with more than that shares
// the neutral mark past it, and those are told apart by picking them -- the
// chip still names each one.
function renderTopologyLegend(el, ranked, slotOf, selected, problemCount = 0) {
    if (!ranked.length) {
        el.innerHTML = '<span class="diagram-legend-empty">No packets</span>';
        return;
    }
    const chip = (attrs, pressed, inner, title) =>
        `<button type="button" class="diagram-legend-item diagram-legend-chip" ${attrs} ` +
        `aria-pressed="${pressed}" title="${escHtml(title)}">${inner}</button>`;
    const items = [chip('data-all="1"', selected.size === 0, "All", "Play every protocol (clears the picks)")];
    if (problemCount) {
        items.push(chip('data-problems="1"', selected.has(PROBLEMS_KEY),
            `<span class="diagram-problem-icon" aria-hidden="true">⚠</span>Problems (${problemCount.toLocaleString()})`,
            "Resets, retransmissions, fragments, ICMP errors and malformed packets -- click to add them to " +
            "the next play, alone or alongside picked protocols"));
    }
    for (const [proto, count] of ranked) {
        const on = selected.has(proto);
        items.push(chip(`data-proto="${escHtml(proto)}"`, on,
            `${slotSwatch(protocolSlot(slotOf, proto))}${escHtml(proto)} (${count.toLocaleString()})`,
            on ? `Picked: click to drop ${proto} from the next play`
                : `Click to add ${proto} to the next play -- pick as many as you like`));
    }
    const help = "Pick one or more protocols: each click adds or drops one, and the next " +
        "play shows only the picked traffic. All clears the picks.";
    el.innerHTML = `<span class="diagram-legend-hint" title="${escHtml(help)}">` +
        `Pick one or more to play <span class="diagram-legend-help" aria-hidden="true">ⓘ</span></span>` +
        items.join("");
}

// Which capture, and which saved view if one is open, in the dialog's title:
// with several captures open in tabs, "Traffic Diagram" alone does not say
// which one is being drawn. The display filter itself stays on the line below.
function renderDiagramContext(kind) {
    const el = $(`${kind}-context`);
    if (!el) return;
    const capture = captures.find((c) => c.id === viewingCaptureId);
    const view = activeViewId === ALL_PACKETS_VIEW ? null : savedViews.find((v) => v.id === activeViewId);
    el.innerHTML = `<span class="diagram-context-capture">${escHtml(capture?.name || viewingCaptureId)}</span>` +
        (view ? `<span class="diagram-context-view">View: ${escHtml(view.name)}</span>` : "");
}

// Shared by both diagrams: the display filter's own packet count decides
// whether this renders at all. Truncating a diagram silently would just draw
// a wrong picture, so above the cap this returns overCap instead of a
// partial result. One request, one tshark pass (see the diagram-packets
// route); the server says what the cap came to, since its ceiling is a
// setting. `cap` is omitted to take that ceiling as it stands.
async function fetchPacketsCapped(captureId, filter, cap) {
    // Reads the same page-level "Resolve hostnames" toggle the packet list
    // uses (frontend/index.html's #resolve-names) -- one setting, not a
    // second copy of it in every dialog that fetches packets. It has to be
    // decided before a diagram loads: a reverse-DNS query per address is not
    // something to fire off mid-animation because someone flipped a switch.
    const params = new URLSearchParams({
        display_filter: filter, resolve_names: resolveNamesEnabled() ? "true" : "false",
    });
    if (cap) params.set("limit", String(cap));
    const res = await api(`/api/captures/${captureId}/diagram-packets?${params}`);
    const limit = res.cap || cap || PACKET_DIAGRAM_CAP;
    if (res.total > limit) return { overCap: true, total: res.total, cap: limit };
    return { overCap: false, total: res.total, cap: limit, packets: res.packets };
}

// The Capture tab's two checkboxes: whether each diagram holds to its packet
// cap (TOPOLOGY_PACKET_CAP, PACKET_DIAGRAM_CAP). Unticked sends no limit, so
// only the server's max_capture_packets applies. Kept per browser; both
// start ticked.
const DIAGRAM_CAP_TOGGLES = ["topology-cap-enabled", "sequence-cap-enabled"];

function diagramPacketLimit(id, cap) {
    return $(id)?.checked === false ? undefined : cap;
}

function initDiagramLimits() {
    for (const id of DIAGRAM_CAP_TOGGLES) {
        const box = $(id);
        if (!box) continue;
        try {
            box.checked = localStorage.getItem(`diagram-cap-off:${id}`) !== "1";
        } catch { /* storage blocked: the cap stays on */ }
        box.addEventListener("change", () => {
            try {
                if (box.checked) localStorage.removeItem(`diagram-cap-off:${id}`);
                else localStorage.setItem(`diagram-cap-off:${id}`, "1");
            } catch { /* kept for this page only */ }
        });
    }
}

function showDiagramCapWarning(kind, total, cap, filter, what = kind === "topology" ? "hosts" : "packets") {
    const box = $(`${kind}-cap-warning`);
    // Only the packet cap is the operator's to lift, and only while its
    // checkbox is ticked; the host and lane caps are fixed.
    const lift = what === "packets" && $(`${kind}-cap-enabled`)?.checked;
    const raise = lift ? ", untick this diagram's max packets on the Capture tab," : "";
    box.textContent = `${total.toLocaleString()} ${what} match ` +
        `${filter ? `"${filter}"` : "the whole capture"} -- above the ${cap.toLocaleString()} this diagram ` +
        `can render. Narrow the display filter${raise} or open a saved view, and try again.`;
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
//
// It lays out in its own coordinates and is never squeezed to fit the
// window: it used to be, by scaling the positions but not the circles, which
// is exactly what piled circles on top of each other. Fitting is now the
// view's job (fitTopologyView), which scales everything alike. `spacing`
// stretches the ideal link length for the Spacing control.
function runForceLayout(nodes, edges, width, height, spacing = 1) {
    if (!nodes.length) return;
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const cx = width / 2;
    const cy = height / 2;
    const seedRadius = Math.min(width, height) * 0.35 * spacing;
    nodes.forEach((n, i) => {
        const angle = (i / nodes.length) * Math.PI * 2;
        n.x = cx + Math.cos(angle) * seedRadius;
        n.y = cy + Math.sin(angle) * seedRadius;
    });
    const idealLen = spacing * Math.min(width, height) / Math.max(4, Math.sqrt(nodes.length));
    const iterations = nodes.length > 80 ? 80 : 150;
    // A hub's spokes all want the same length, so they bunch into a tight
    // starburst around it. Give each link room in proportion to how many
    // links its busier end has: a host with sixteen neighbours holds them
    // further out than one with two.
    const degree = new Map(nodes.map((n) => [n.id, 0]));
    for (const e of edges) {
        if (degree.has(e.a)) degree.set(e.a, degree.get(e.a) + 1);
        if (degree.has(e.b)) degree.set(e.b, degree.get(e.b) + 1);
    }
    const edgeLen = (e) => idealLen * (0.7 + 0.3 * Math.sqrt(Math.max(degree.get(e.a) || 1, degree.get(e.b) || 1)));

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
            const force = (dist - edgeLen(e)) * 0.02;
            const fxv = (dx / dist) * force, fyv = (dy / dist) * force;
            fx.set(a.id, fx.get(a.id) + fxv); fy.set(a.id, fy.get(a.id) + fyv);
            fx.set(b.id, fx.get(b.id) - fxv); fy.set(b.id, fy.get(b.id) - fyv);
        }

        const cooling = 1 - it / iterations;
        const maxStep = 40 * spacing * cooling + 1;
        for (const n of nodes) {
            const fxv = fx.get(n.id) + (cx - n.x) * 0.01;
            const fyv = fy.get(n.id) + (cy - n.y) * 0.01;
            n.x += clamp(-maxStep, fxv, maxStep);
            n.y += clamp(-maxStep, fyv, maxStep);
        }
    }

    separateNodes(nodes);
}

// Roughly how wide a node's address label draws (11px monospace).
const NODE_LABEL_CHAR_PX = 6.8;

// The box a node needs to itself: its circle, the address label to its
// right, and room underneath for the most-used-protocol badge. `scale` is
// the glyph scale it will be drawn at (glyphScale): zoomed out, a node takes
// up more of the layout, because it keeps its size on screen.
function nodeBox(n, scale = 1) {
    const labelChars = n.id.length + (n.ifaceText ? n.ifaceText.length + 2 : 0);
    return {
        left: n.x - (n.r + 4) * scale,
        right: n.x + (n.r + 8 + labelChars * NODE_LABEL_CHAR_PX) * scale,
        top: n.y - (n.r + 4) * scale,
        bottom: n.y + (n.r + 20) * scale,
    };
}

// The force layout spaces centres, not what is drawn around them, so a big
// circle or a long hostname still lands on a neighbour. This pushes any two
// overlapping boxes apart along whichever axis needs the smaller move, a few
// passes over, until nothing overlaps (or the pass budget runs out).
function separateNodes(nodes, scale = 1, passes = 60) {
    for (let pass = 0; pass < passes; pass++) {
        let moved = false;
        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const a = nodes[i], b = nodes[j];
                const A = nodeBox(a, scale), B = nodeBox(b, scale);
                const ox = Math.min(A.right, B.right) - Math.max(A.left, B.left);
                const oy = Math.min(A.bottom, B.bottom) - Math.max(A.top, B.top);
                if (ox <= 0 || oy <= 0) continue;
                moved = true;
                if (ox < oy) {
                    const d = (ox / 2 + 1) * (a.x <= b.x ? -1 : 1);
                    a.x += d; b.x -= d;
                } else {
                    const d = (oy / 2 + 1) * (a.y <= b.y ? -1 : 1);
                    a.y += d; b.y -= d;
                }
            }
        }
        if (!moved) return;
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

// --- Zoom and pan -------------------------------------------------------------
//
// One view transform, {k, tx, ty}, maps layout coordinates to the drawing
// area: the SVG gets it as a transform on the group holding every node and
// edge, and the canvas applies it by hand to each packet mark's position
// (only the position -- a mark stays the same size at every zoom, so it is
// still readable zoomed right out).

const ZOOM_MIN = 0.1;
const ZOOM_MAX = 6;
const ZOOM_STEP = 1.25;

function toScreen(view, x, y) {
    return { x: view.tx + x * view.k, y: view.ty + y * view.k };
}

function toWorld(view, pt) {
    return { x: (pt.x - view.tx) / view.k, y: (pt.y - view.ty) / view.k };
}

// Zoomed out, a node -- circle, address, badge -- keeps its on-screen size
// and only the distances between nodes shrink, so labels stay readable at
// any zoom. Zoomed in past 100% everything grows together.
function glyphScale() {
    const k = topologyState?.view.k ?? 1;
    return k < 1 ? 1 / k : 1;
}

function placeNode(n) {
    n.el?.setAttribute("transform", `translate(${n.x},${n.y}) scale(${glyphScale()})`);
}

function applyTopologyView() {
    if (!topologyState) return;
    const { k, tx, ty } = topologyState.view;
    topologyState.world.setAttribute("transform", `translate(${tx},${ty}) scale(${k})`);
    topologyState.nodes.forEach(placeNode);
    placeOverlays();
    const label = $("topology-zoom-level");
    if (label) label.textContent = `${Math.round(k * 100)}%`;
    redrawTopologyFrame();
}

// Zooms so every node, label included, is in view -- never past 100%, so a
// two-host capture is not blown up to fill the screen. Node glyphs keep their
// screen size when zoomed out (glyphScale), so the fit is worked out on the
// node centres, with each glyph's own extent added in screen pixels.
// `floor` is the furthest out it will go. The Fit button passes none, and so
// always shows everything. The automatic view (settleAndFit, a resize) stops
// at the zoom the layout was separated for: below it the glyphs would overlap,
// so a graph that does not fit there is shown from its busiest host, to be
// panned, rather than squeezed into a heap.
function fitTopologyView(floor = ZOOM_MIN) {
    if (!topologyState) return;
    const { width, height } = topologyState;
    const nodes = topologyState.nodes.filter((n) => !n.hidden);
    const pad = 24;
    let minX = 0, maxX = width, minY = 0, maxY = height;
    let left = 0, right = 0, top = 0, bottom = 0;
    if (nodes.length) {
        minX = minY = Infinity; maxX = maxY = -Infinity;
        for (const n of nodes) {
            const b = nodeBox(n);
            minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
            minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
            left = Math.max(left, n.x - b.left); right = Math.max(right, b.right - n.x);
            top = Math.max(top, n.y - b.top); bottom = Math.max(bottom, b.bottom - n.y);
        }
    }
    const spanX = Math.max(1, maxX - minX), spanY = Math.max(1, maxY - minY);
    const k = clamp(ZOOM_MIN, Math.min(
        (width - pad * 2 - left - right) / spanX, (height - pad * 2 - top - bottom) / spanY, 1,
    ), ZOOM_MAX);
    if (k < floor && nodes.length) {
        const hub = nodes.reduce((best, n) => (n.bytes > best.bytes ? n : best), nodes[0]);
        topologyState.view = { k: floor, tx: width / 2 - hub.x * floor, ty: height / 2 - hub.y * floor, userMoved: false };
        applyTopologyView();
        return;
    }
    topologyState.view = {
        k,
        tx: (width + left - right - spanX * k) / 2 - minX * k,
        ty: (height + top - bottom - spanY * k) / 2 - minY * k,
        userMoved: false,
    };
    applyTopologyView();
}

// Fitting zooms out, and zoomed out each node's glyph takes more of the
// layout than separateNodes allowed for -- so neighbours that cleared each
// other at 100% overlap at 78%. Separate once more at the zoom the fit landed
// on (a little over, since spreading lowers the zoom again) and refit.
//
// Once, and capped: repeating it runs away -- each round spreads the layout,
// which zooms the fit further out, which grows the glyphs again -- and a few
// rounds of that stacked a capture into a single column. A graph too big for
// the window at readable size is what Spacing, zoom and pan are for.
const SETTLE_MAX_SCALE = 1.6;

const AUTO_ZOOM_FLOOR = 1 / SETTLE_MAX_SCALE;

function settleAndFit() {
    fitTopologyView();
    if (topologyState.view.k >= 1) return;
    const { nodes, edgeLayer, byId } = topologyState;
    separateNodes(nodes, Math.min(glyphScale() * 1.1, SETTLE_MAX_SCALE));
    updateEdgePositions(edgeLayer, byId);
    fitTopologyView(AUTO_ZOOM_FLOOR);
}

// Shows the layout at 100% without shrinking it to fit -- what a wider
// Spacing is for -- centred on the busiest host, which is where a starburst
// has its middle. Fit (or zooming out) still shows the whole of it.
function centerTopologyView() {
    const { nodes, width, height } = topologyState;
    const hub = nodes.reduce((best, n) => (n.bytes > best.bytes ? n : best), nodes[0]);
    topologyState.view = { k: 1, tx: width / 2 - hub.x, ty: height / 2 - hub.y, userMoved: true };
    applyTopologyView();
}

// Zoom by `factor`, keeping the layout point under (px, py) where it is --
// the pointer for the wheel, the centre for the buttons.
function zoomTopology(factor, px, py) {
    if (!topologyState) return;
    const v = topologyState.view;
    const k = clamp(ZOOM_MIN, v.k * factor, ZOOM_MAX);
    if (px === undefined) { px = topologyState.width / 2; py = topologyState.height / 2; }
    v.tx = px - (px - v.tx) * (k / v.k);
    v.ty = py - (py - v.ty) * (k / v.k);
    v.k = k;
    v.userMoved = true;
    applyTopologyView();
}

// Wheel to zoom, and drag on the empty background to pan. A drag that starts
// on a node moves the node (makeDraggable); one that starts on a link is left
// alone, since a click there filters the packet list.
function initTopologyZoomPan(svg) {
    svg.addEventListener("wheel", (ev) => {
        if (!topologyState) return;
        ev.preventDefault();
        const pt = svgPoint(svg, ev);
        zoomTopology(ev.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP, pt.x, pt.y);
    }, { passive: false });

    let pan = null;
    svg.addEventListener("pointerdown", (ev) => {
        if (!topologyState || ev.target !== svg) return;
        const pt = svgPoint(svg, ev);
        pan = { x: pt.x, y: pt.y, tx: topologyState.view.tx, ty: topologyState.view.ty };
        svg.setPointerCapture(ev.pointerId);
        svg.classList.add("is-panning");
    });
    svg.addEventListener("pointermove", (ev) => {
        if (!pan) return;
        const pt = svgPoint(svg, ev);
        const v = topologyState.view;
        v.tx = pan.tx + (pt.x - pan.x);
        v.ty = pan.ty + (pt.y - pan.y);
        v.userMoved = true;
        applyTopologyView();
    });
    const end = () => { pan = null; svg.classList.remove("is-panning"); };
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);
}

// Full screen is the dialog itself, where the browser allows it. Where it does
// not (an iPhone has no element full screen), the class alone still stretches
// the dialog edge to edge.
async function toggleTopologyFullscreen() {
    const dialog = $("topology-dialog");
    const on = !dialog.classList.contains("is-fullscreen");
    dialog.classList.toggle("is-fullscreen", on);
    $("btn-topology-fullscreen").setAttribute("aria-pressed", String(on));
    try {
        if (on && dialog.requestFullscreen && !document.fullscreenElement) await dialog.requestFullscreen();
        else if (!on && document.fullscreenElement) await document.exitFullscreen();
    } catch { /* refused (no user gesture, or not allowed): the class still applies */ }
}

function onTopologyFullscreenChange() {
    const dialog = $("topology-dialog");
    // Esc leaves browser full screen without going through the button.
    if (!document.fullscreenElement && dialog?.classList.contains("is-fullscreen")) {
        dialog.classList.remove("is-fullscreen");
        $("btn-topology-fullscreen").setAttribute("aria-pressed", "false");
    }
}

// --- Its own window ---------------------------------------------------------
//
// "New window" opens the same app at a URL whose hash names a capture, and
// that page shows nothing but this diagram, edge to edge -- one to keep on a
// second screen while the packet list stays in the first. Same origin, so the
// session cookie comes along and there is no second sign-in. Every value read
// back from the hash is checked against what the server returned for this
// user (the capture and view ids) or against the page's own options (spacing)
// before it is used, so a hand-edited link can only ever pick among them.

const DIAGRAM_WINDOW_HASH = "#traffic-diagram?";

function diagramWindowUrl() {
    const params = new URLSearchParams({
        capture: viewingCaptureId,
        filter: $("display-filter").value.trim(),
        spacing: $("topology-spacing").value,
        names: resolveNamesEnabled() ? "1" : "0",
    });
    if (activeViewId !== ALL_PACKETS_VIEW) params.set("view", activeViewId);
    return `${location.origin}/${DIAGRAM_WINDOW_HASH}${params}`;
}

function openTopologyInNewWindow() {
    if (!viewingCaptureId) return;
    window.open(diagramWindowUrl(), "_blank", "noopener");
}

function diagramWindowParams() {
    return location.hash.startsWith(DIAGRAM_WINDOW_HASH)
        ? new URLSearchParams(location.hash.slice(DIAGRAM_WINDOW_HASH.length))
        : null;
}

// Called by app.js enterApp, once signed in, when the page was opened as a
// diagram window.
async function openDiagramWindow(params) {
    document.body.classList.add("diagram-window");
    await loadCaptures();
    const capture = captures.find((c) => c.id === params.get("capture"));
    if (!capture) {
        leaveDiagramWindow();
        return;
    }
    viewingCaptureId = capture.id;
    $("display-filter").value = params.get("filter") || "";
    const names = $("resolve-names");
    if (names) names.checked = params.get("names") === "1";
    const spacing = $("topology-spacing");
    if ([...spacing.options].some((o) => o.value === params.get("spacing"))) spacing.value = params.get("spacing");
    if (params.get("view")) {
        try {
            savedViews = await api(`/api/captures/${encodeURIComponent(capture.id)}/views`);
        } catch { savedViews = []; }
        activeViewId = savedViews.some((v) => v.id === params.get("view")) ? params.get("view") : ALL_PACKETS_VIEW;
    }
    document.title = `Traffic Diagram: ${capture.name || capture.id}`;
    $("topology-dialog").classList.add("is-fullscreen");
    await openTopologyDialog();
}

// Closing the diagram closes its window. A browser that will not let a page
// close itself gets the ordinary app instead of an empty page.
function leaveDiagramWindow() {
    window.close();
    document.body.classList.remove("diagram-window");
    history.replaceState(null, "", "/");
}

// The page's own "Resolve hostnames" setting, switched from the diagram: the
// two are one setting, so the packet list follows (outside a diagram-only
// window, where there is no packet list to reload). The diagram reopens to
// fetch its hosts again, named or not.
function onTopologyResolveToggle() {
    const names = $("resolve-names");
    if (!names) return;
    names.checked = $("topology-resolve").checked;
    if (!document.body.classList.contains("diagram-window")) onResolveNamesToggled();
    openTopologyDialog();
}

// Re-lays the graph out at the chosen spacing. Positions only: the SVG
// elements (and any badges on them) stay. Normal fits the window; anything
// wider is shown at 100% and centred -- refitting it would only shrink the
// spread back to the same picture -- and is there to be panned around.
function onTopologySpacingChange() {
    if (!topologyState) return;
    const spacing = parseFloat($("topology-spacing").value) || 1;
    const { nodes, edges, width, height } = topologyState;
    runForceLayout(nodes, edges, width, height, spacing);
    updateEdgePositions(topologyState.edgeLayer, topologyState.byId);
    if (spacing > 1 && nodes.length) centerTopologyView();
    else settleAndFit();
}

function updateEdgePositions(edgeLayer, byId) {
    for (const line of edgeLayer.children) {
        const a = byId.get(line.dataset.a), b = byId.get(line.dataset.b);
        if (!a || !b) continue;
        line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
        line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    }
    placeOverlays();
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
        const world = topologyState ? toWorld(topologyState.view, pt) : pt;
        node.x = world.x; node.y = world.y;
        if (topologyState) topologyState.userDragged = true;
        placeNode(node);
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
// updateEdgePositions during playback and drag, and the group the zoom and
// pan transform goes on.
function renderTopologySVG(svg, nodes, byId, edges, onNodeClick, onEdgeClick) {
    svg.innerHTML = "";
    const width = svg.clientWidth || 800, height = svg.clientHeight || 500;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const world = svgEl("g", { class: "diagram-world" });
    const edgeLayer = svgEl("g", { class: "diagram-edges" });
    const nodeLayer = svgEl("g", { class: "diagram-nodes" });
    world.append(edgeLayer, nodeLayer);
    svg.append(world);

    for (const e of edges) {
        const a = byId.get(e.a), b = byId.get(e.b);
        if (!a || !b) continue;
        const line = svgEl("line", {
            class: "diagram-edge", x1: a.x, y1: a.y, x2: b.x, y2: b.y, "stroke-width": e.width,
        });
        line.dataset.a = e.a; line.dataset.b = e.b; line.dataset.baseWidth = e.width;
        line.addEventListener("click", () => onEdgeClick(e));
        const title = svgEl("title");
        title.textContent = `${e.a} <-> ${e.b}: ${formatBytes(e.totalBytes)}, ` +
            `${(e.packetsAB + e.packetsBA).toLocaleString()} pkts\nClick to filter the packet list to this conversation`;
        line.append(title);
        edgeLayer.append(line);
    }

    for (const n of nodes) {
        const g = svgEl("g", { class: "diagram-node", transform: `translate(${n.x},${n.y})` });
        const circle = svgEl("circle", { r: n.r });
        const label = svgEl("text", { x: n.r + 4, y: 4 });
        label.textContent = n.id;
        const title = svgEl("title");
        title.textContent = `${n.id}: ${formatBytes(n.bytes)}, ${n.packets.toLocaleString()} pkts` +
            "\nClick to filter the packet list to this host, or drag to move it";
        g.append(circle, label, title);
        g.addEventListener("click", () => { if (g.dataset.dragged === undefined) onNodeClick(n); });
        // The packet marks live on the canvas, not in this <g>, so a drag has
        // to repaint them too -- otherwise, paused or finished, the marks
        // sitting on a node stay where the node used to be.
        makeDraggable(g, n, () => { updateEdgePositions(edgeLayer, byId); redrawTopologyFrame(); });
        n.el = g;
        nodeLayer.append(g);
    }

    return { edgeLayer, world };
}

// --- Interfaces per host (captures on "any" only) ---------------------------
//
// Only a Linux cooked capture -- one taken on "any" -- records which interface
// each packet crossed (app.js hides the Interface column everywhere else for
// the same reason), so for any other capture every packet's interface is
// empty and nothing is drawn. The names come from the packets, which the
// dialog fetches as it opens; Play reuses that fetch rather than repeating it.

// The one fetch of this dialog's packets, shared by the prefetch and Play.
function topologyPackets() {
    if (!topologyState.packetsPromise) {
        const state = topologyState;
        state.packetsPromise = fetchPacketsCapped(state.captureId, state.filter, diagramPacketLimit("topology-cap-enabled", TOPOLOGY_PACKET_CAP));
        // A failed fetch is not kept: the next press of Play tries again.
        state.packetsPromise.catch(() => { state.packetsPromise = null; });
    }
    return topologyState.packetsPromise;
}

// Fetched as the dialog opens, for every capture: the stats pane's protocol
// table, the protocol chips and (on "any" captures) the interface labels all
// come from the packets, and should not wait for someone to press Play.
function prefetchTopologyPackets() {
    const state = topologyState;
    topologyPackets().then((result) => {
        // Over the cap, Play says so when pressed; until then the graph just
        // goes without the packet-derived extras.
        if (topologyState === state && !result.overCap) preparePlayback(result.packets);
    }, () => { /* Play reports a failed fetch; nothing to add here */ });
}

// At most two names inline, then "+N" -- the full list is in the <title>.
const NODE_IFACE_INLINE = 2;

function computeNodeInterfaces(packets) {
    const perHost = new Map();
    const add = (host, iface) => {
        if (!iface) return;
        if (!perHost.has(host)) perHost.set(host, new Set());
        perHost.get(host).add(iface);
    };
    for (const p of packets) { add(p.source, p.interface); add(p.destination, p.interface); }
    return perHost;
}

// Drawn as a quieter second half of the address label, on the same line, so a
// node gains no extra row of text -- and inside the node's <g>, so it drags
// with it.
function showNodeInterfaces(packets) {
    if (!topologyState || topologyState.interfacesShown) return;
    const perHost = computeNodeInterfaces(packets);
    if (!perHost.size) return;
    topologyState.interfacesShown = true;
    for (const n of topologyState.nodes) {
        const names = [...(perHost.get(n.id) || [])].sort();
        if (!names.length || !n.el) continue;
        const shown = names.slice(0, NODE_IFACE_INLINE).join(" · ");
        const more = names.length - NODE_IFACE_INLINE;
        n.ifaceText = more > 0 ? `${shown} +${more}` : shown;
        const label = n.el.querySelector(":scope > text");
        const span = svgEl("tspan", { class: "diagram-node-iface", dx: 6 });
        span.textContent = n.ifaceText;
        label.append(span);
        const title = n.el.querySelector(":scope > title");
        const [head, ...rest] = title.textContent.split("\n");
        title.textContent = [head, `Interfaces: ${names.join(", ")}`, ...rest].join("\n");
    }
    // The labels just got longer: make room for them. A layout the user has
    // already dragged about is left as they arranged it.
    if (!topologyState.userDragged) {
        separateNodes(topologyState.nodes);
        topologyState.nodes.forEach(placeNode);
        updateEdgePositions(topologyState.edgeLayer, topologyState.byId);
        if (!topologyState.view.userMoved) settleAndFit();
        else redrawTopologyFrame();
    }
}

// --- Most-used protocol per host, shown when a play reaches its end ---------

// Per host, which protocol it sent or received most often among `packets`.
// A tie goes to the protocol that is more common across the whole play, so
// two hosts tied the same way never disagree about which one is shown.
function computeTopProtocols(packets, ranked) {
    const rank = new Map(ranked.map(([proto], i) => [proto, i]));
    const perHost = new Map();
    const bump = (host, proto) => {
        if (!perHost.has(host)) perHost.set(host, new Map());
        const counts = perHost.get(host);
        counts.set(proto, (counts.get(proto) || 0) + 1);
    };
    for (const p of packets) {
        bump(p.source, p.protocol);
        if (p.destination !== p.source) bump(p.destination, p.protocol);
    }
    const top = new Map();
    for (const [host, counts] of perHost) {
        let best = null;
        let total = 0;
        for (const [proto, count] of counts) {
            total += count;
            if (!best || count > best.count ||
                (count === best.count && (rank.get(proto) ?? Infinity) < (rank.get(best.proto) ?? Infinity))) {
                best = { proto, count };
            }
        }
        top.set(host, { ...best, total });
    }
    return top;
}

function slotMarkEl(slot, r) {
    const attrs = { fill: slot.color, class: "diagram-node-top-mark" };
    if (slot.shape === "square") return svgEl("rect", { ...attrs, x: -r, y: -r, width: r * 2, height: r * 2 });
    if (slot.shape === "diamond") {
        const d = r * 1.3;
        return svgEl("path", { ...attrs, d: `M0,${-d} L${d},0 L0,${d} L${-d},0 Z` });
    }
    if (slot.shape === "triangle") {
        const d = r * 1.3;
        return svgEl("path", { ...attrs, d: `M0,${-d} L${d},${d * 0.8} L${-d},${d * 0.8} Z` });
    }
    if (slot.shape === "ring") {
        return svgEl("circle", { ...attrs, r, fill: "none", stroke: slot.color, "stroke-width": 2 });
    }
    return svgEl("circle", { ...attrs, r });
}

// Drawn inside each node's own <g>, under the circle, so it moves with the
// node when it is dragged -- the canvas marks are repainted on drag, but a
// label that belongs to a host should not need repainting to stay on it.
function showTopProtocolBadges(playback) {
    hideTopProtocolBadges();
    if (!topologyState) return;
    const top = computeTopProtocols(playback.packets, playback.ranked);
    for (const n of topologyState.nodes) {
        const best = top.get(n.id);
        if (!best || !n.el) continue;
        const slot = protocolSlot(playback.slotOf, best.proto);
        const badge = svgEl("g", { class: "diagram-node-top", transform: `translate(0,${n.r + 11})` });
        const text = svgEl("text", { x: 8, y: 4 });
        text.textContent = best.proto;
        const title = svgEl("title");
        const pct = Math.round((best.count / best.total) * 100);
        title.textContent = `${n.id}: most used ${best.proto}, ` +
            `${best.count.toLocaleString()} of ${best.total.toLocaleString()} packets (${pct}%)`;
        badge.append(slotMarkEl(slot, 4), text, title);
        n.el.append(badge);
    }
}

function hideTopProtocolBadges() {
    document.querySelectorAll("#topology-svg .diagram-node-top").forEach((el) => el.remove());
}

function playbackAtEnd(playback) {
    return playback.progress >= playback.packets.length;
}

// --- Stats pane ---------------------------------------------------------------

function statsRow(label, value, title = "") {
    return `<tr${title ? ` title="${escHtml(title)}"` : ""}><th scope="row">${escHtml(label)}</th>` +
        `<td>${escHtml(value)}</td></tr>`;
}

function statsSection(heading, rows) {
    return rows.length
        ? `<h4>${escHtml(heading)}</h4><table class="diagram-stats-table">${rows.join("")}</table>`
        : "";
}

function percent(part, whole) {
    return whole ? `${Math.round((part / whole) * 100)}%` : "";
}

// Everything here is computed from what the dialog already holds -- the
// /conversations answer for the graph, and the packets Play fetched -- so the
// pane costs no request of its own.
function renderTopologyStats() {
    const el = $("topology-stats-body");
    if (!el) return;
    if (!topologyState) { el.innerHTML = ""; return; }
    const { nodes, edges } = topologyState;
    const totalPackets = edges.reduce((s, e) => s + e.packetsAB + e.packetsBA, 0);
    const totalBytes = edges.reduce((s, e) => s + e.totalBytes, 0);
    const parts = [];
    const sel = topologyState.selection;
    if (sel) {
        const heading = sel.kind === "host" ? `Selected host ${sel.id}` : `Selected link ${sel.a} ↔ ${sel.b}`;
        const sp = topologyState.selectionProtocols;
        const rows = sp
            ? [statsRow("Packets", sp.total.toLocaleString()), ...sp.list.map(([proto, c]) =>
                `<tr><th scope="row">${slotSwatch(protocolSlot(topologyState.rank.slotOf, proto))}` +
                `${escHtml(proto)}</th><td>${escHtml(`${c.toLocaleString()} · ${percent(c, sp.total)}`)}</td></tr>`)]
            : [statsRow("Protocols", "loading…")];
        parts.push(statsSection(heading, rows));
    }
    const pbp = topologyPlayback;
    if (pbp?.problemCounts) {
        const rows = PROBLEM_KINDS.filter((k) => pbp.problemCounts.get(k.key)).map((k) =>
            `<tr class="diagram-stats-action" data-problem="${k.key}" tabindex="0" ` +
            `title="Filter the packet list to these: ${escHtml(k.filter)}">` +
            `<th scope="row"><span class="diagram-problem-icon" aria-hidden="true">⚠</span>${escHtml(k.label)}</th>` +
            `<td>${pbp.problemCounts.get(k.key).toLocaleString()}</td></tr>`);
        parts.push(statsSection("Problems", rows.length ? rows : [statsRow("None found", "")]));
    }
    parts.push(statsSection("Capture", [
        statsRow("Hosts", nodes.length.toLocaleString()),
        statsRow("Links", edges.length.toLocaleString()),
        // From /conversations, which counts IP traffic only -- so an ARP-heavy
        // capture shows fewer here than in the play below. Labelled as such.
        statsRow("IP packets", totalPackets.toLocaleString()),
        statsRow("IP bytes", formatBytes(totalBytes)),
    ]));

    const pb = topologyPlayback;
    if (pb) {
        const counts = new Map();
        for (const p of pb.packets) counts.set(p.protocol, (counts.get(p.protocol) || 0) + 1);
        const rows = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)
            .map(([proto, c]) => statsRow(proto, `${c.toLocaleString()} · ${percent(c, pb.packets.length)}`));
        const scope = pb.selected.size ? "This play" : "Protocols";
        parts.push(statsSection(scope, [statsRow("Packets", pb.packets.length.toLocaleString()), ...rows]));
    }

    const talkers = [...nodes].sort((a, b) => b.bytes - a.bytes).slice(0, 5)
        .map((n) => statsRow(n.id, formatBytes(n.bytes), `${n.packets.toLocaleString()} packets`));
    parts.push(statsSection("Top talkers", talkers));

    const links = [...edges].sort((a, b) => b.totalBytes - a.totalBytes).slice(0, 5)
        .map((e) => statsRow(`${e.a} ↔ ${e.b}`, formatBytes(e.totalBytes),
            `${(e.packetsAB + e.packetsBA).toLocaleString()} packets`));
    parts.push(statsSection("Busiest links", links));

    el.innerHTML = parts.join("");
}

const STATS_OPEN_KEY = "pcap.topologyStatsOpen";

function onTopologyStatsAction(ev) {
    const row = ev.target.closest("[data-problem]");
    if (!row || (ev.type === "keydown" && ev.key !== "Enter")) return;
    const kind = PROBLEM_KINDS.find((k) => k.key === row.dataset.problem);
    if (kind) filterViewerTo(kind.filter);
}

function initTopologyStatsToggle() {
    const pane = $("topology-stats");
    if (!pane) return;
    try {
        if (localStorage.getItem(STATS_OPEN_KEY) === "0") pane.open = false;
    } catch { /* storage blocked: the pane just opens every time */ }
    pane.addEventListener("toggle", () => {
        try { localStorage.setItem(STATS_OPEN_KEY, pane.open ? "1" : "0"); } catch { /* ignore */ }
    });
}

// Opening or closing the stats pane, going full screen, or resizing the
// window changes the drawing area. The SVG would rescale itself, but the
// canvas is a fixed bitmap stretched to fit, so the two would stop lining up.
// Both are resized to the new area instead. The layout itself is untouched:
// if the user has not zoomed or panned it refits, otherwise the view stays
// where they put it.
function resizeTopology() {
    if (!topologyState) return;
    const svg = $("topology-svg");
    const width = svg.clientWidth, height = svg.clientHeight;
    if (!width || !height || (width === topologyState.width && height === topologyState.height)) return;
    topologyState.width = width; topologyState.height = height;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const canvas = $("topology-canvas");
    canvas.width = width; canvas.height = height;
    if (topologyState.view.userMoved) applyTopologyView();
    else fitTopologyView(AUTO_ZOOM_FLOOR);
}

function redrawTopologyFrame() {
    if (!topologyPlayback || !topologyState) return;
    const canvas = $("topology-canvas");
    drawTopologyFrame(canvas.getContext("2d"), canvas, topologyPlayback);
}

// A link that carried problem packets gets a red badge with their count, a
// third of the way along it (the middle is where a selected link lists its
// protocols). Hovering says which kinds; clicking filters the packet list to
// just those packets on just that link.
function renderProblemBadges(packets) {
    const state = topologyState;
    state.world.querySelector(".diagram-problem-badges")?.remove();
    const perLink = new Map();
    for (const p of packets) {
        const kind = PROBLEM_OF.get(p);
        if (!kind) continue;
        const key = linkKey(p.source, p.destination);
        if (!perLink.has(key)) perLink.set(key, { a: p.source, b: p.destination, kinds: new Map(), total: 0 });
        const entry = perLink.get(key);
        entry.kinds.set(kind, (entry.kinds.get(kind) || 0) + 1);
        entry.total++;
    }
    if (!perLink.size) return;
    const layer = svgEl("g", { class: "diagram-problem-badges" });
    for (const entry of perLink.values()) {
        if (!state.byId.has(entry.a) || !state.byId.has(entry.b)) continue;
        const g = svgEl("g", { class: "diagram-problem-badge" });
        g.dataset.a = entry.a; g.dataset.b = entry.b;
        const text = String(entry.total);
        const w = 12 + text.length * 7;
        g.append(
            svgEl("rect", { x: -w / 2, y: -8, width: w, height: 16, rx: 8 }),
            Object.assign(svgEl("text", { x: 0, y: 4, "text-anchor": "middle" }), { textContent: `⚠${text}` }),
        );
        const title = svgEl("title");
        title.textContent = `${entry.a} ↔ ${entry.b}: ` +
            [...entry.kinds].map(([k, c]) => `${c.toLocaleString()} ${k.label.toLowerCase()}`).join(", ") +
            "\nClick to filter the packet list to them";
        g.append(title);
        g.addEventListener("click", () => {
            const field = addressField(entry.a);
            if (!field) return;
            const kinds = [...entry.kinds.keys()].map((k) => `(${k.filter})`).join(" || ");
            filterViewerTo(`${buildFieldFilter(field, entry.a)} && ${buildFieldFilter(field, entry.b)} && (${kinds})`);
        });
        layer.append(g);
    }
    state.world.append(layer);
    placeProblemBadges();
}

function placeProblemBadges() {
    const state = topologyState;
    if (!state) return;
    const s = glyphScale();
    for (const g of state.world.querySelectorAll(".diagram-problem-badge")) {
        const a = state.byId.get(g.dataset.a), b = state.byId.get(g.dataset.b);
        if (!a || !b) continue;
        g.setAttribute("transform", `translate(${a.x + (b.x - a.x) / 3},${a.y + (b.y - a.y) / 3}) scale(${s})`);
    }
}

// --- Finding a host --------------------------------------------------------
//
// The search box across the top of the diagram: matching hosts light up and
// everything else fades; Enter steps through the matches, centring each and
// zooming in to at least 100% so its label is readable; Escape clears it.
// Matches on what the node is labelled with -- the address, or the name when
// names are resolved -- and on its interfaces.

function onTopologySearch() {
    const state = topologyState;
    if (!state) return;
    const q = $("topology-search").value.trim().toLowerCase();
    const matches = q
        ? state.nodes.filter((n) => !n.hidden && (n.id.toLowerCase().includes(q) ||
            (n.ifaceText || "").toLowerCase().includes(q)))
        : [];
    const hit = new Set(matches.map((n) => n.id));
    for (const n of state.nodes) {
        n.el?.classList.toggle("is-match", hit.has(n.id));
        n.el?.classList.toggle("is-dimmed", Boolean(q) && !hit.has(n.id));
    }
    for (const line of state.edgeLayer.children) {
        line.classList.toggle("is-dimmed", Boolean(q) && !hit.has(line.dataset.a) && !hit.has(line.dataset.b));
    }
    state.search = { matches, index: -1 };
    $("topology-search-count").textContent = !q ? ""
        : !matches.length ? "No host matches"
            : `${matches.length} host${matches.length === 1 ? "" : "s"} · Enter to go to ${matches.length === 1 ? "it" : "each"}`;
}

function onTopologySearchKey(ev) {
    const state = topologyState;
    if (!state) return;
    if (ev.key === "Escape") {
        // Clears the box first; a second Escape closes the dialog as usual.
        if ($("topology-search").value) {
            ev.preventDefault();
            $("topology-search").value = "";
            onTopologySearch();
        }
        return;
    }
    if (ev.key !== "Enter" || !state.search?.matches.length) return;
    ev.preventDefault();
    const { matches } = state.search;
    state.search.index = (state.search.index + 1) % matches.length;
    const n = matches[state.search.index];
    const v = state.view;
    v.k = Math.max(v.k, 1);
    v.tx = state.width / 2 - n.x * v.k;
    v.ty = state.height / 2 - n.y * v.k;
    v.userMoved = true;
    applyTopologyView();
    $("topology-search-count").textContent =
        `${state.search.index + 1} of ${matches.length}: ${n.id} · Enter for the next`;
}

// --- Clicking a host or a link ---------------------------------------------
//
// A click filters the packet list to that host or conversation and leaves the
// diagram open, so the two can be read side by side: the diagram marks what
// was clicked, lists every protocol it carried, and says which filter the
// packet list now has. A second click on the same thing clears the mark (the
// filter stays; the viewer's own filter box is where it is changed).
//
// In a diagram-only window there is no packet list in the page, so the
// filter goes to the app's other tabs over a BroadcastChannel -- same-origin
// by construction -- and a tab viewing the same capture applies it. What
// arrives is checked (a string, for the capture that tab has open) and only
// ever lands in the display filter box, where it is exactly as trusted as
// something typed there.

const DIAGRAM_CHANNEL = "pcap-server-diagram";
let diagramChannel = null;

function diagramBroadcast() {
    if (!diagramChannel && window.BroadcastChannel) diagramChannel = new BroadcastChannel(DIAGRAM_CHANNEL);
    return diagramChannel;
}

function onDiagramBroadcast(ev) {
    const m = ev.data;
    if (document.body.classList.contains("diagram-window")) return;
    if (!m || m.type !== "filter" || typeof m.filter !== "string" || typeof m.capture !== "string") return;
    if (m.capture !== viewingCaptureId) return;
    applyBuiltFilter(m.filter, "selected");
}

function filterViewerTo(expr) {
    if (document.body.classList.contains("diagram-window")) {
        diagramBroadcast()?.postMessage({ type: "filter", capture: topologyState.captureId, filter: expr });
    } else {
        applyBuiltFilter(expr, "selected");
    }
    const inWindow = document.body.classList.contains("diagram-window");
    $("topology-selection").textContent =
        `${inWindow ? "Sent to the app's packet list" : "Packet list filtered to"}: ${expr}`;
}

function onTopologyNodeClick(n) {
    const field = addressField(n.id);
    if (!field) return;
    filterViewerTo(buildFieldFilter(field, n.id));
    selectTopologyItem({ kind: "host", id: n.id });
}

function onTopologyEdgeClick(e) {
    const field = addressField(e.a);
    if (!field) return;
    filterViewerTo(`${buildFieldFilter(field, e.a)} && ${buildFieldFilter(field, e.b)}`);
    selectTopologyItem({ kind: "link", a: e.a, b: e.b });
}

function sameSelection(x, y) {
    return x && y && x.kind === y.kind && x.id === y.id && x.a === y.a && x.b === y.b;
}

function selectionMatches(sel, p) {
    if (sel.kind === "host") return p.source === sel.id || p.destination === sel.id;
    return (p.source === sel.a && p.destination === sel.b) || (p.source === sel.b && p.destination === sel.a);
}

async function selectTopologyItem(sel) {
    const state = topologyState;
    if (!state) return;
    state.selection = sameSelection(state.selection, sel) ? null : sel;
    const cur = state.selection;
    for (const n of state.nodes) {
        n.el?.classList.toggle("is-selected", Boolean(cur && cur.kind === "host" && cur.id === n.id));
    }
    for (const line of state.edgeLayer.children) {
        const { a, b } = line.dataset;
        line.classList.toggle("is-selected", Boolean(cur && cur.kind === "link" &&
            ((cur.a === a && cur.b === b) || (cur.a === b && cur.b === a))));
    }
    state.selectionProtocols = null;
    renderSelectionOverlay();
    renderTopologyStats();
    if (!cur) return;
    // Every protocol the host or conversation carried, from the capture's
    // packets -- the same fetch Play uses, so at most one per dialog.
    let result;
    try { result = await topologyPackets(); } catch { return; }
    if (topologyState !== state || state.selection !== cur || result.overCap) return;
    if (!state.rank) state.rank = rankProtocols(result.packets, TOPOLOGY_SLOT_CAP);  // before preparePlayback
    const counts = new Map();
    let total = 0;
    for (const p of result.packets) {
        if (!selectionMatches(cur, p)) continue;
        counts.set(p.protocol, (counts.get(p.protocol) || 0) + 1);
        total++;
    }
    state.selectionProtocols = { total, list: [...counts.entries()].sort((x, y) => y[1] - x[1]) };
    renderSelectionOverlay();
    renderTopologyStats();
}

// A selected link carries a row of every protocol that crossed it, at its
// midpoint and inside the zoomed group, so it follows drags and zoom.
function renderSelectionOverlay() {
    const state = topologyState;
    state?.world.querySelector(".diagram-link-protocols")?.remove();
    const sel = state?.selection;
    if (!sel || sel.kind !== "link" || !state.selectionProtocols) return;
    const g = svgEl("g", { class: "diagram-link-protocols" });
    let x = 0;
    for (const [proto] of state.selectionProtocols.list) {
        const mark = slotMarkEl(protocolSlot(state.rank.slotOf, proto), 4);
        mark.setAttribute("transform", `translate(${x + 4},0)`);
        const text = svgEl("text", { x: x + 11, y: 4 });
        text.textContent = proto;
        g.append(mark, text);
        x += 20 + proto.length * NODE_LABEL_CHAR_PX;
    }
    g.dataset.width = String(x);
    state.world.append(g);
    placeOverlays();
}

function placeOverlays() {
    placeProblemBadges();
    const state = topologyState;
    const g = state?.world.querySelector(".diagram-link-protocols");
    if (!g || !state.selection) return;
    const a = state.byId.get(state.selection.a), b = state.byId.get(state.selection.b);
    if (!a || !b) return;
    const s = glyphScale();
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    g.setAttribute("transform",
        `translate(${mx - (Number(g.dataset.width) / 2) * s},${my - 12 * s}) scale(${s})`);
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
    renderDiagramContext("topology");
    $("topology-resolve").checked = resolveNamesEnabled();
    $("topology-selection").textContent = "";
    $("topology-search").value = "";
    $("topology-search-count").textContent = "";
    $("topology-cap-warning").hidden = true;
    $("topology-body").hidden = false;
    $("topology-legend").innerHTML =
        '<span class="diagram-legend-empty">Press Play to animate packet flow, colored by protocol</span>';
    resetTopologyPlayback();
    topologyState = null;
    renderTopologyStats();
    $("topology-svg").innerHTML = "";
    const canvas = $("topology-canvas");
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    dialog.showModal();
    try {
        const data = await api(
            `/api/captures/${viewingCaptureId}/conversations?${new URLSearchParams({
                display_filter: filter, resolve_names: resolveNamesEnabled() ? "true" : "false",
            })}`
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
        runForceLayout(nodes, edges, width, height, parseFloat($("topology-spacing").value) || 1);
        const byId = new Map(nodes.map((n) => [n.id, n]));
        const { edgeLayer, world } =
            renderTopologySVG(svg, nodes, byId, edges, onTopologyNodeClick, onTopologyEdgeClick);
        topologyState = {
            captureId: viewingCaptureId, filter, nodes, edges, byId, edgeLayer, world, width, height,
            view: { k: 1, tx: 0, ty: 0, userMoved: false },
        };
        settleAndFit();
        renderTopologyStats();
        $("btn-topology-play").disabled = false;
        prefetchTopologyPackets();
        // Speed is a setting, not a playback state: pick it before the first
        // play as easily as during one.
        $("topology-speed").disabled = false;
    } catch (e) {
        $("topology-legend").innerHTML = `<span style="color:var(--danger)">${escHtml(e.message)}</span>`;
    }
}

// Everything a play needs, from the dialog's packets: the protocol ranking
// (and so each protocol's mark), the legend's chips, the stats pane's
// protocol table, interface labels. Done as soon as the packets arrive --
// the dialog fetches them on open -- so all of it is there before the first
// press of Play; Play itself only has to start the clock.
function preparePlayback(packets) {
    if (topologyPlayback) return;
    showNodeInterfaces(packets);
    const { ranked, slotOf } = rankProtocols(packets, TOPOLOGY_SLOT_CAP);
    // Canvas needs literal colors (it cannot resolve var(...)), so the
    // slots are resolved once here rather than per frame. The shape rides
    // along unchanged -- it is the same slot object's field.
    const resolvedSlotOf = new Map(
        [...slotOf].map(([proto, slot]) => [proto, { ...slot, color: resolveColor(slot.color) }])
    );
    // Ranked (and so colored) from every packet, once. Picking protocols
    // narrows what plays but never reshuffles which mark a protocol has.
    topologyPlayback = {
        allPackets: packets, packets, selected: new Set(),
        ranked, slotOf, resolvedSlotOf, playing: false, progress: 0, raf: null,
    };
    topologyState.rank = { ranked, slotOf };
    topologyPlayback.problemCounts = classifyProblems(packets);
    topologyPlayback.problemTotal = [...topologyPlayback.problemCounts.values()].reduce((a, b) => a + b, 0);
    topologyPlayback.dangerColor = resolveColor("var(--danger)") || "#e5484d";
    renderProblemBadges(packets);
    renderTopologyLegend($("topology-legend"), ranked, slotOf, topologyPlayback.selected, topologyPlayback.problemTotal);
    $("topology-scrubber").max = String(packets.length);
    $("topology-scrubber").disabled = false;
    $("topology-speed").disabled = false;
    renderTopologyStats();
}

async function onTopologyPlayClick() {
    if (!topologyState) return;
    if (!topologyPlayback) {
        $("btn-topology-play").disabled = true;
        $("btn-topology-play").textContent = "Loading…";
        let result;
        try {
            result = await topologyPackets();
        } catch (e) {
            $("btn-topology-play").disabled = false;
            $("btn-topology-play").textContent = "Play";
            $("topology-legend").innerHTML = `<span style="color:var(--danger)">${escHtml(e.message)}</span>`;
            return;
        }
        $("btn-topology-play").disabled = false;
        if (result.overCap) {
            showDiagramCapWarning("topology", result.total, result.cap, topologyState.filter, "packets");
            return;
        }
        preparePlayback(result.packets);
    }
    // A finished play has already rewound (finishTopologyPlay), so this
    // starts it over; the last picture and its badges give way to it.
    if (topologyPlayback.finished || playbackAtEnd(topologyPlayback)) {
        topologyPlayback.finished = false;
        topologyPlayback.progress = 0;
        hideTopProtocolBadges();
    }
    topologyPlayback.playing = !topologyPlayback.playing;
    $("btn-topology-play").textContent = topologyPlayback.playing ? "Pause" : "Play";
    if (topologyPlayback.playing) startTopologyAnimation();
}

// Cumulative, not decaying: how many times each link has been crossed by
// the time playback has reached idx.
function computeEdgeHeat(packets, idx) {
    const heat = new Map();
    for (let i = 0; i <= idx && i < packets.length; i++) addEdgeHeat(heat, packets[i]);
    return heat;
}

function addEdgeHeat(heat, p) {
    const key = p.source <= p.destination ? `${p.source}|${p.destination}` : `${p.destination}|${p.source}`;
    heat.set(key, (heat.get(key) || 0) + 1);
}

// computeEdgeHeat carried forward from the last frame rather than redone from
// packet 0 every frame: at a hundred thousand packets the recount was the
// frame. Going backwards (a scrub, a replay) starts over from scratch, so a
// scrub back is exactly as correct as playing forwards.
function edgeHeatAt(playback, idx) {
    let cache = playback.heatCache;
    if (!cache || cache.packets !== playback.packets || idx < cache.idx) {
        cache = playback.heatCache = { packets: playback.packets, idx: -1, heat: new Map() };
    }
    for (let i = cache.idx + 1; i <= idx && i < playback.packets.length; i++) {
        addEdgeHeat(cache.heat, playback.packets[i]);
    }
    cache.idx = Math.max(cache.idx, Math.min(idx, playback.packets.length - 1));
    return cache.heat;
}

// Packets per second at 1x: TOPOLOGY_PACKETS_PER_SECOND_AT_1X, or faster for
// a capture that would otherwise take longer than TOPOLOGY_PLAY_SECONDS_AT_1X.
function playbackRate(total) {
    return Math.max(TOPOLOGY_PACKETS_PER_SECOND_AT_1X, total / TOPOLOGY_PLAY_SECONDS_AT_1X);
}

// The more a link has carried, the brighter and wider it draws -- capped at
// EDGE_HEAT_CAP so the busiest link in a capture reads as "busy", not as a
// single dark bar that has swallowed the rest of the graph.
function applyEdgeHeat(edgeLayer, heat) {
    if (!edgeLayer) return;
    for (const line of edgeLayer.children) {
        const a = line.dataset.a, b = line.dataset.b;
        const key = a <= b ? `${a}|${b}` : `${b}|${a}`;
        const t = Math.min(heat.get(key) || 0, EDGE_HEAT_CAP) / EDGE_HEAT_CAP;
        const base = Number(line.dataset.baseWidth) || 1;
        line.style.strokeWidth = String(base + t * 4);
        line.style.strokeOpacity = String(0.35 + t * 0.65);
    }
}

function drawTopologyFrame(ctx, canvas, playback) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    // A finished play has rewound its progress but still shows its last frame.
    const progress = playback.finished ? playback.packets.length : playback.progress;
    const idx = Math.floor(progress);
    const view = topologyState.view;
    applyEdgeHeat(topologyState?.edgeLayer, edgeHeatAt(playback, idx));
    const trailStart = Math.max(0, idx - 20);
    for (let i = trailStart; i <= idx && i < playback.packets.length; i++) {
        const p = playback.packets[i];
        const a = topologyState.byId.get(p.source), b = topologyState.byId.get(p.destination);
        if (!a || !b) continue;
        const frac = i === idx ? progress - idx : 1;
        const { x, y } = toScreen(view, a.x + (b.x - a.x) * frac, a.y + (b.y - a.y) * frac);
        ctx.globalAlpha = Math.max(0.08, 1 - (idx - i) / 20);
        const slot = playback.resolvedSlotOf.get(p.protocol);
        drawPacketMark(ctx, x, y, slot ? slot.color : "#888", slot ? slot.shape : "circle");
        if (PROBLEM_OF.has(p)) {
            // A reset, retransmission, fragment ... wears a red ring on top of
            // its protocol mark, so trouble stands out mid-play.
            ctx.beginPath();
            ctx.arc(x, y, PACKET_MARK_R + 4, 0, Math.PI * 2);
            ctx.lineWidth = 2;
            ctx.strokeStyle = playback.dangerColor;
            ctx.stroke();
        }
    }
    ctx.globalAlpha = 1;
}

// One packet on the canvas. The shape is half of what identifies its protocol
// (see PROTOCOL_SLOTS), so it is drawn a little larger than the 4px circle
// this used to be -- a 4px square and a 4px circle are the same smudge.
//
// The ring is the surface gap two overlapping marks need to stay two marks. It
// is painted from the canvas's own backdrop rather than a fixed color so it
// works in both themes, and it goes UNDER the fill so it never eats into the
// shape it is separating.
const PACKET_MARK_R = 5;

function drawPacketMark(ctx, x, y, color, shape) {
    const r = PACKET_MARK_R;
    const trace = () => {
        ctx.beginPath();
        if (shape === "square") {
            ctx.rect(x - r, y - r, r * 2, r * 2);
        } else if (shape === "diamond") {
            ctx.moveTo(x, y - r * 1.3);
            ctx.lineTo(x + r * 1.3, y);
            ctx.lineTo(x, y + r * 1.3);
            ctx.lineTo(x - r * 1.3, y);
            ctx.closePath();
        } else if (shape === "triangle") {
            ctx.moveTo(x, y - r * 1.3);
            ctx.lineTo(x + r * 1.3, y + r * 1.05);
            ctx.lineTo(x - r * 1.3, y + r * 1.05);
            ctx.closePath();
        } else {
            ctx.arc(x, y, r, 0, Math.PI * 2);
        }
    };
    trace();
    ctx.lineWidth = shape === "ring" ? 5 : 2;
    ctx.strokeStyle = resolveColor("var(--bg-primary)") || "#000";
    ctx.stroke();
    trace();
    if (shape === "ring") {
        // Hollow: the outline is the mark, so it is drawn thick enough to
        // carry the hue, over a wider backdrop ring for the surface gap.
        ctx.lineWidth = 2.5;
        ctx.strokeStyle = color;
        ctx.stroke();
    } else {
        ctx.fillStyle = color;
        ctx.fill();
    }
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
        const total = topologyPlayback.packets.length;
        topologyPlayback.progress += dt * playbackRate(total) * speed;
        if (topologyPlayback.progress >= total) {
            finishTopologyPlay(topologyPlayback);
            return;
        }
        $("topology-scrubber").value = String(Math.floor(topologyPlayback.progress));
        updatePlaybackCount(topologyPlayback);
        drawTopologyFrame(ctx, canvas, topologyPlayback);
        if (topologyPlayback.playing) topologyPlayback.raf = requestAnimationFrame(frame);
    }
    topologyPlayback.raf = requestAnimationFrame(frame);
}

// The end of a play: the picture stays on its last frame, with each host's
// most-used protocol under it, but the play itself goes back to the start so
// the next press of Play replays it rather than finding nothing left.
function finishTopologyPlay(playback) {
    playback.playing = false;
    playback.finished = true;
    playback.progress = playback.packets.length;
    redrawTopologyFrame();
    showTopProtocolBadges(playback);
    playback.progress = 0;
    $("btn-topology-play").textContent = "Play";
    $("topology-scrubber").value = "0";
    $("topology-playback-count").textContent = `Done: ${playback.packets.length.toLocaleString()} packets`;
}

function onTopologyScrub() {
    if (!topologyPlayback) return;
    topologyPlayback.finished = false;
    topologyPlayback.playing = false;
    $("btn-topology-play").textContent = "Play";
    topologyPlayback.progress = Number($("topology-scrubber").value);
    updatePlaybackCount(topologyPlayback);
    redrawTopologyFrame();
    if (playbackAtEnd(topologyPlayback)) showTopProtocolBadges(topologyPlayback);
    else hideTopProtocolBadges();
}

// With protocols picked, hosts and links that carried none of them go
// from the drawing: what is left is the part of the network that traffic
// actually used. Nothing picked shows everything again.
function applyProtocolScope(packets, scoped) {
    const hosts = new Set();
    const links = new Set();
    for (const p of packets) {
        hosts.add(p.source); hosts.add(p.destination);
        links.add(p.source <= p.destination ? `${p.source}|${p.destination}` : `${p.destination}|${p.source}`);
    }
    for (const n of topologyState.nodes) {
        n.hidden = scoped && !hosts.has(n.id);
        n.el?.classList.toggle("is-hidden", n.hidden);
    }
    for (const el of [...topologyState.edgeLayer.children, ...topologyState.world.querySelectorAll(".diagram-problem-badge")]) {
        const { a, b } = el.dataset;
        el.classList.toggle("is-hidden", scoped && !links.has(linkKey(a, b)));
    }
    if (!topologyState.view.userMoved) fitTopologyView(AUTO_ZOOM_FLOOR);
}

// A protocol chip was clicked: change the selection, and rewind to a stopped
// play of just those packets, ready for the next press of Play.
function onTopologyLegendClick(ev) {
    const chip = ev.target.closest(".diagram-legend-chip");
    const pb = topologyPlayback;
    if (!chip || !pb) return;
    const sel = pb.selected;
    const key = chip.dataset.problems ? PROBLEMS_KEY : chip.dataset.proto;
    if (chip.dataset.all) sel.clear();
    else if (sel.has(key)) sel.delete(key);
    else sel.add(key);
    pb.packets = sel.size
        ? pb.allPackets.filter((p) => sel.has(p.protocol) || (sel.has(PROBLEMS_KEY) && PROBLEM_OF.has(p)))
        : pb.allPackets;
    pb.playing = false;
    pb.finished = false;
    if (pb.raf) cancelAnimationFrame(pb.raf);
    pb.progress = 0;
    $("btn-topology-play").textContent = "Play";
    $("topology-scrubber").max = String(pb.packets.length);
    $("topology-scrubber").value = "0";
    $("topology-playback-count").textContent = "";
    hideTopProtocolBadges();
    applyEdgeHeat(topologyState?.edgeLayer, new Map());
    const canvas = $("topology-canvas");
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    renderTopologyLegend($("topology-legend"), pb.ranked, pb.slotOf, sel, pb.problemTotal);
    applyProtocolScope(pb.packets, sel.size > 0);
    renderTopologyStats();
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
    return { hosts, laneX, laneGap, rowGap, topPad, totalHeight: topPad + packets.length * rowGap + 30 };
}

// .seq-lane-label is 11px monospace; a monospace glyph is ~0.6em wide.
const LANE_LABEL_CHAR_PX = 6.8;

// A centred label may use the gap to its neighbours and twice its distance to
// either edge -- past that it runs off the diagram (the leftmost lane sits
// 80px in, so a resolved hostname clipped there) or into the next label.
function laneLabelRoom(x, width, laneGap) {
    return Math.min(laneGap - 8, 2 * x - 8, 2 * (width - x) - 8);
}

// Shortened in the middle, not the end: a hostname is told apart by its first
// label and an address by its last octets, and a middle cut keeps both. The
// full name rides in the label's <title>.
function fitLaneLabel(host, roomPx) {
    const max = Math.max(5, Math.floor(roomPx / LANE_LABEL_CHAR_PX));
    if (host.length <= max) return host;
    const tail = Math.floor((max - 1) / 2);
    return `${host.slice(0, max - 1 - tail)}…${host.slice(host.length - tail)}`;
}

function renderSequenceSVG(svg, packets, slotOf) {
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
        const room = laneLabelRoom(x, width, layout.hosts.length > 1 ? layout.laneGap : Infinity);
        label.textContent = fitLaneLabel(host, room);
        if (label.textContent !== host) {
            const full = svgEl("title");
            full.textContent = host;
            label.append(full);
        }
        laneLayer.append(label);
    }

    packets.forEach((p, i) => {
        const y = layout.topPad + i * layout.rowGap;
        const x1 = layout.laneX.get(p.source), x2 = layout.laneX.get(p.destination);
        const slot = protocolSlot(slotOf, p.protocol);
        const d = x1 === x2 ? `M${x1 - 12},${y} L${x1 + 12},${y}` : `M${x1},${y} L${x2},${y}`;
        const attrs = {
            class: "seq-arrow", d, stroke: slot.color, "stroke-width": 1.5,
            "marker-end": "url(#seq-arrowhead)",
        };
        // A lane's worth of dashes is what tells two same-hue protocols apart
        // here, since a line has no shape to vary. The arrowhead stays solid:
        // it inherits context-stroke, not the dash pattern.
        if (slot.dash) attrs["stroke-dasharray"] = slot.dash;
        const path = svgEl("path", attrs);
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
    renderDiagramContext("sequence");
    $("sequence-cap-warning").hidden = true;
    $("sequence-body").hidden = false;
    $("sequence-legend").innerHTML = '<span class="diagram-legend-empty"><span class="spinner"></span></span>';
    $("sequence-svg").innerHTML = "";
    dialog.showModal();
    try {
        const result = await fetchPacketsCapped(viewingCaptureId, filter, diagramPacketLimit("sequence-cap-enabled", PACKET_DIAGRAM_CAP));
        if (result.overCap) {
            showDiagramCapWarning("sequence", result.total, result.cap, filter);
            return;
        }
        if (!result.packets.length) {
            $("sequence-legend").innerHTML = '<span class="diagram-legend-empty">No packets</span>';
            return;
        }
        // A lane per host is the whole idea of this view -- past a few dozen
        // it stops being one. Guarded the same way the packet cap is: block
        // and ask for a narrower filter rather than draw something this
        // cramped that nobody could actually read.
        const hosts = new Set();
        for (const p of result.packets) { hosts.add(p.source); hosts.add(p.destination); }
        if (hosts.size > SEQUENCE_LANE_CAP) {
            showDiagramCapWarning("sequence", hosts.size, SEQUENCE_LANE_CAP, filter, "hosts");
            return;
        }
        const { ranked, slotOf } = rankProtocols(result.packets);
        renderLegend($("sequence-legend"), ranked, slotOf);
        renderSequenceSVG($("sequence-svg"), result.packets, slotOf);
    } catch (e) {
        $("sequence-legend").innerHTML = `<span style="color:var(--danger)">${escHtml(e.message)}</span>`;
    }
}

// --- wiring -------------------------------------------------------------

function initDiagramDialogs() {
    initDiagramLimits();
    for (const id of ["topology-dialog", "sequence-dialog"]) {
        const dialog = $(id);
        dialog?.addEventListener("click", (e) => {
            if (e.target.closest("[data-close-dialog]")) dialog.close();
        });
    }
    $("topology-dialog")?.addEventListener("close", () => {
        if (document.body.classList.contains("diagram-window")) leaveDiagramWindow();
        $("topology-dialog").classList.remove("is-fullscreen");
        $("btn-topology-fullscreen")?.setAttribute("aria-pressed", "false");
        if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
        if (!topologyPlayback) return;
        topologyPlayback.playing = false;
        if (topologyPlayback.raf) cancelAnimationFrame(topologyPlayback.raf);
    });
    $("btn-topology")?.addEventListener("click", openTopologyDialog);
    $("btn-sequence")?.addEventListener("click", openSequenceDialog);
    $("btn-topology-play")?.addEventListener("click", onTopologyPlayClick);
    $("topology-scrubber")?.addEventListener("input", onTopologyScrub);
    $("topology-legend")?.addEventListener("click", onTopologyLegendClick);
    $("btn-topology-zoom-in")?.addEventListener("click", () => zoomTopology(ZOOM_STEP));
    $("btn-topology-zoom-out")?.addEventListener("click", () => zoomTopology(1 / ZOOM_STEP));
    $("btn-topology-fit")?.addEventListener("click", () => fitTopologyView());
    $("btn-topology-fullscreen")?.addEventListener("click", toggleTopologyFullscreen);
    $("btn-topology-new-window")?.addEventListener("click", openTopologyInNewWindow);
    $("topology-spacing")?.addEventListener("change", onTopologySpacingChange);
    $("topology-resolve")?.addEventListener("change", onTopologyResolveToggle);
    $("topology-search")?.addEventListener("input", onTopologySearch);
    $("topology-search")?.addEventListener("keydown", onTopologySearchKey);
    $("topology-stats-body")?.addEventListener("click", onTopologyStatsAction);
    $("topology-stats-body")?.addEventListener("keydown", onTopologyStatsAction);
    diagramBroadcast()?.addEventListener("message", onDiagramBroadcast);
    document.addEventListener("fullscreenchange", onTopologyFullscreenChange);
    if ($("topology-svg")) initTopologyZoomPan($("topology-svg"));
    initTopologyStatsToggle();
    const wrap = $("topology-svg")?.parentElement;
    if (wrap && window.ResizeObserver) new ResizeObserver(resizeTopology).observe(wrap);
    const seqSvg = $("sequence-svg");
    if (seqSvg) initSequenceInteractions(seqSvg);
}

initDiagramDialogs();
