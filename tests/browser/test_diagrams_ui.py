"""Traffic Diagram (topology graph) and Sequence Diagram (swimlanes).

Same shape as tests/browser/test_stats_dialogs_ui.py: window.api is stubbed
for the routes under test, and these tests are about the browser side --
does the SVG draw what the route hands back, and do its click targets do the
right thing. The force layout and the playback animation are not asserted on
directly (they're geometry, not correctness); what matters is that the right
number of nodes/edges/lanes/arrows appear and that clicking one does what it
should.
"""

from __future__ import annotations

from tests.browser.conftest import needs_browser

pytestmark = needs_browser


async def _stub_api(page, path_fragment: str, response):
    await page.evaluate(
        """([fragment, response]) => {
            const real = window.api;
            window.api = async (path, opts) => {
                if (path.includes(fragment)) return response;
                return real(path, opts);
            };
        }""",
        [path_fragment, response],
    )


async def _open_viewer(page, capture_id: str = "cap-1"):
    await page.evaluate(
        """(id) => {
            viewingCaptureId = id;
            activatePanel("viewer");
            hide("viewer-empty");
            show("packet-viewer");
        }""",
        capture_id,
    )


def _packet(number, source, destination, protocol="TCP", info="x"):
    return {
        "number": number, "timestamp": "0.0", "source": source, "destination": destination,
        "protocol": protocol, "length": 66, "info": info, "src_mac": "", "dst_mac": "",
        "interface": "", "ifindex": 0, "direction": "", "tcp_stream": None, "udp_stream": None,
    }


CONVERSATIONS_PAYLOAD = {
    "conversations": [{
        "a": "10.0.0.1", "b": "10.0.0.2",
        "packets_a_to_b": 4, "bytes_a_to_b": 253,
        "packets_b_to_a": 3, "bytes_b_to_a": 205,
    }],
    "endpoints": [
        {"address": "10.0.0.1", "packets": 4, "bytes": 253},
        {"address": "10.0.0.2", "packets": 3, "bytes": 205},
    ],
}


async def test_topology_renders_nodes_and_edges(app_page):
    await _stub_api(app_page, "/conversations", CONVERSATIONS_PAYLOAD)
    await _open_viewer(app_page)

    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-dialog[open]")

    assert await app_page.locator("#topology-svg .diagram-node").count() == 2
    assert await app_page.locator("#topology-svg .diagram-edge").count() == 1
    # The static graph never fetches packets -- Play does that, on demand.
    assert await app_page.is_disabled("#btn-topology-play") is False


def _click_node(page, address):
    return page.evaluate(
        """(address) => {
            const g = [...document.querySelectorAll('.diagram-node')]
                .find((n) => n.querySelector('text').textContent === address);
            g.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        }""",
        address,
    )


async def test_topology_node_click_filters_the_packet_list_and_stays_open(app_page):
    await _stub_api(app_page, "/conversations", CONVERSATIONS_PAYLOAD)
    await _open_viewer(app_page)

    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-dialog[open]")
    await _click_node(app_page, "10.0.0.1")

    assert await app_page.input_value("#display-filter") == "ip.addr == 10.0.0.1"
    assert await app_page.locator("#topology-dialog[open]").count() == 1
    assert await app_page.locator("#topology-svg .diagram-node.is-selected").count() == 1
    assert "ip.addr == 10.0.0.1" in await app_page.inner_text("#topology-selection")


async def test_a_link_click_filters_to_the_conversation_and_lists_all_its_protocols(app_page):
    packets = [
        _packet(1, "10.0.0.1", "10.0.0.2", "DNS"),
        _packet(2, "10.0.0.2", "10.0.0.1", "TLS"),
        _packet(3, "10.0.0.1", "10.0.0.2", "TLS"),
        _packet(4, "10.0.0.1", "10.0.0.2", "HTTP"),
    ]
    await _open_topology_with_packets(app_page, packets)
    await app_page.evaluate(
        "() => document.querySelector('#topology-svg .diagram-edge').dispatchEvent(new MouseEvent('click', { bubbles: true }))")

    assert await app_page.input_value("#display-filter") == "ip.addr == 10.0.0.1 && ip.addr == 10.0.0.2"
    assert await app_page.locator("#topology-dialog[open]").count() == 1
    await app_page.wait_for_selector("#topology-svg .diagram-link-protocols text")
    on_link = await app_page.eval_on_selector_all(
        "#topology-svg .diagram-link-protocols text", "els => els.map(e => e.textContent)")
    assert on_link == ["TLS", "DNS", "HTTP"]
    stats = await app_page.inner_text("#topology-stats-body")
    assert "selected link" in stats.lower() and "HTTP" in stats

    # A second click on the same link clears the mark; the filter stays.
    await app_page.evaluate(
        "() => document.querySelector('#topology-svg .diagram-edge').dispatchEvent(new MouseEvent('click', { bubbles: true }))")
    assert await app_page.locator("#topology-svg .diagram-link-protocols").count() == 0
    assert await app_page.input_value("#display-filter") == "ip.addr == 10.0.0.1 && ip.addr == 10.0.0.2"


async def test_topology_cap_warning_when_hosts_exceed_the_limit(app_page):
    payload = {
        "conversations": [],
        "endpoints": [{"address": f"10.0.0.{i}", "packets": 1, "bytes": 1} for i in range(201)],
    }
    await _stub_api(app_page, "/conversations", payload)
    await _open_viewer(app_page)

    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-dialog[open]")

    assert await app_page.is_visible("#topology-cap-warning")
    assert "201" in await app_page.inner_text("#topology-cap-warning")
    assert await app_page.is_hidden("#topology-body")


async def test_sequence_renders_one_lane_per_host(app_page):
    payload = {
        "packets": [
            _packet(1, "10.0.0.1", "10.0.0.2", "TCP"),
            _packet(2, "10.0.0.2", "10.0.0.1", "UDP"),
            _packet(3, "10.0.0.1", "10.0.0.3", "DNS"),
        ],
        "total": 3,
    }
    await _stub_api(app_page, "/diagram-packets?", payload)
    await _open_viewer(app_page)

    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")

    assert await app_page.locator("#sequence-svg .seq-lane-line").count() == 3
    assert await app_page.locator("#sequence-svg .seq-arrow").count() == 3
    legend = await app_page.inner_text("#sequence-legend")
    assert "TCP" in legend and "UDP" in legend and "DNS" in legend


async def test_sequence_arrow_click_opens_the_packet_and_closes(app_page):
    payload = {"packets": [_packet(7, "10.0.0.1", "10.0.0.2")], "total": 1}
    await _stub_api(app_page, "/diagram-packets?", payload)
    await _stub_api(app_page, "/packets/7", {"layers": [], "frame_hex": ""})
    await _open_viewer(app_page)

    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")
    await app_page.evaluate(
        """() => document.querySelector('#sequence-svg .seq-arrow')
            .dispatchEvent(new MouseEvent('click', { bubbles: true }))"""
    )

    assert await app_page.locator("#sequence-dialog[open]").count() == 0
    # selectPacket's own visible effect: setDetailVisible(true) drops
    # no-selection from the viewer, whether or not frame 7's row happens to
    # be on the current packet-list page.
    no_selection = await app_page.evaluate(
        "() => document.getElementById('packet-viewer').classList.contains('no-selection')"
    )
    assert no_selection is False


async def test_topology_and_play_pass_resolve_names_when_checked(app_page):
    await app_page.evaluate(
        """(response) => {
            window.__calls = [];
            const real = window.api;
            window.api = async (path, opts) => {
                window.__calls.push(path);
                if (path.includes('/conversations')) return response.conv;
                if (path.includes('/diagram-packets?')) return response.pkts;
                return real(path, opts);
            };
        }""",
        {
            "conv": CONVERSATIONS_PAYLOAD,
            "pkts": {"packets": [_packet(1, "10.0.0.1", "10.0.0.2")], "total": 1},
        },
    )
    await _open_viewer(app_page)
    # #resolve-names lives inside the capture-flags panel, collapsed by
    # default in this test's bare viewer state -- setting it directly is
    # equivalent to a visible click for what's under test here, which is
    # only whether diagrams.js reads it (resolveNamesEnabled), not the
    # panel's own disclosure behaviour (covered elsewhere).
    await app_page.evaluate(
        """() => {
            const el = document.getElementById('resolve-names');
            el.checked = true;
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
    )

    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-dialog[open]")
    await app_page.click("#btn-topology-play")
    await app_page.wait_for_function("() => !document.getElementById('btn-topology-play').disabled")

    calls = await app_page.evaluate("() => window.__calls")
    assert any("/conversations" in c and "resolve_names=true" in c for c in calls)
    assert any("/diagram-packets?" in c and "resolve_names=true" in c for c in calls)


async def test_sequence_cap_warning_when_hosts_exceed_the_limit(app_page):
    # 25 packets, each between a distinct pair -- 50 hosts, past the 40-lane cap.
    payload = {
        "packets": [_packet(i, f"10.0.0.{i}", f"10.0.1.{i}") for i in range(25)],
        "total": 25,
    }
    await _stub_api(app_page, "/diagram-packets?", payload)
    await _open_viewer(app_page)

    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")

    assert await app_page.is_visible("#sequence-cap-warning")
    assert "hosts" in await app_page.inner_text("#sequence-cap-warning")
    assert await app_page.is_hidden("#sequence-body")


async def test_edge_heat_climbs_with_crossings_and_stays_capped(app_page):
    # computeEdgeHeat itself is an uncapped count -- the cap is applied only
    # where it's drawn, in applyEdgeHeat, so a crossing count is never lost.
    raw_count = await app_page.evaluate(
        """() => {
            const packets = Array.from({ length: 30 }, () => ({ source: 'a', destination: 'b' }));
            return computeEdgeHeat(packets, packets.length - 1).get('a|b');
        }"""
    )
    assert raw_count == 30

    styled = await app_page.evaluate(
        """() => {
            const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            line.dataset.a = 'a'; line.dataset.b = 'b'; line.dataset.baseWidth = '1';
            const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            g.appendChild(line);
            applyEdgeHeat(g, new Map([['a|b', 999]]));
            return { width: line.style.strokeWidth, opacity: line.style.strokeOpacity };
        }"""
    )
    assert styled["width"] == "5"      # base 1 + the full +4 bonus, never more
    assert styled["opacity"] == "1"    # 0.35 + the full 0.65 bonus, never more


async def test_sequence_cap_warning_when_packets_exceed_the_limit(app_page):
    await _stub_api(app_page, "/diagram-packets?", {"packets": [], "total": 10001})
    await _open_viewer(app_page)

    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")

    assert await app_page.is_visible("#sequence-cap-warning")
    assert "10,001" in await app_page.inner_text("#sequence-cap-warning") \
        or "10001" in await app_page.inner_text("#sequence-cap-warning")
    assert await app_page.is_hidden("#sequence-body")


async def test_the_legend_holds_eight_protocols_each_a_distinct_mark(app_page):
    """Eight slots from three validated hues times three shapes: the ninth
    protocol and beyond fold into "Other", and no two named entries share
    both a hue and a shape -- that pairing is what identifies a protocol."""
    protocols = ["TCP", "UDP", "DNS", "TLS", "HTTP", "ICMP", "ARP", "NTP", "SNMP", "SSH"]
    packets, n = [], 0
    # Descending counts, so the ranking (and so the cut at eight) is fixed.
    for rank, proto in enumerate(protocols):
        for _ in range(len(protocols) - rank):
            n += 1
            packets.append(_packet(n, "10.0.0.1", "10.0.0.2", proto))
    await _stub_api(app_page, "/diagram-packets?", {"packets": packets, "total": len(packets)})
    await _open_viewer(app_page)

    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")

    items = app_page.locator("#sequence-legend .diagram-legend-item")
    assert await items.count() == 9
    labels = [t.split(" (")[0] for t in await items.all_inner_texts()]
    assert labels == protocols[:8] + ["Other"]
    assert "(3)" in (await items.nth(8).inner_text()), "SNMP (2) + SSH (1) fold into Other"

    marks = await app_page.eval_on_selector_all(
        "#sequence-legend .diagram-legend-item svg",
        """els => els.slice(0, 8).map(svg => [
            svg.getAttribute('fill'),
            svg.lastElementChild.tagName.toLowerCase() === 'path' ? 'diamond'
                : svg.lastElementChild.tagName.toLowerCase(),
        ].join('|'))""",
    )
    assert len(set(marks)) == 8, marks


async def test_a_long_lane_label_is_shortened_to_fit_and_keeps_its_full_name(app_page):
    """The leftmost lane sits 80px in, so a resolved hostname centred on it ran
    off the diagram's left edge. It is cut in the middle, and the full name is
    one hover away in its <title>."""
    long_name = "SHIELD-BASEMENT.a-rather-long-internal-domain.example.net"
    payload = {
        "packets": [_packet(1, long_name, "10.0.0.2", "DNS"), _packet(2, "10.0.0.2", long_name, "DNS")],
        "total": 2,
    }
    await _stub_api(app_page, "/diagram-packets?", payload)
    await _open_viewer(app_page)
    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")

    label = app_page.locator("#sequence-svg .seq-lane-label").first
    text = await label.evaluate("el => el.firstChild.textContent")
    assert "…" in text and text.startswith("SHIELD") and text.endswith("net")
    assert await label.locator("title").text_content() == long_name

    inside = await app_page.evaluate("""() => {
        const svg = document.getElementById('sequence-svg').getBoundingClientRect();
        return [...document.querySelectorAll('#sequence-svg .seq-lane-label')].every(t => {
            const b = t.getBoundingClientRect();
            return b.left >= svg.left - 0.5 && b.right <= svg.right + 0.5;
        });
    }""")
    assert inside


async def test_a_short_lane_label_is_left_whole(app_page):
    payload = {"packets": [_packet(1, "10.0.0.1", "10.0.0.2", "TCP")], "total": 1}
    await _stub_api(app_page, "/diagram-packets?", payload)
    await _open_viewer(app_page)
    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")
    labels = await app_page.eval_on_selector_all(
        "#sequence-svg .seq-lane-label", "els => els.map(e => e.textContent)"
    )
    assert labels == ["10.0.0.1", "10.0.0.2"]
    assert await app_page.locator("#sequence-svg .seq-lane-label title").count() == 0


async def test_closed_dialogs_are_not_laid_out(app_page):
    """.stats-dialog's display:flex used to outrank the browser's hiding rule,
    so every closed dialog was rendered below the app shell -- widening a
    phone's page and leaving its buttons reachable by Tab."""
    await app_page.set_viewport_size({"width": 390, "height": 844})
    shown = await app_page.eval_on_selector_all(
        "dialog:not([open])", "els => els.filter(d => getComputedStyle(d).display !== 'none').map(d => d.id)"
    )
    assert shown == []
    widths = await app_page.evaluate(
        "() => [document.scrollingElement.scrollWidth, document.documentElement.clientWidth]"
    )
    assert widths[0] <= widths[1], f"page is {widths[0]}px wide in a {widths[1]}px viewport"


# --- Traffic Diagram: protocol picker, end-of-play badges, stats, zoom -------

PLAY_PACKETS = [
    _packet(1, "10.0.0.1", "10.0.0.2", "DNS"),
    _packet(2, "10.0.0.2", "10.0.0.1", "DNS"),
    _packet(3, "10.0.0.1", "10.0.0.2", "TLS"),
    _packet(4, "10.0.0.1", "10.0.0.2", "TLS"),
    _packet(5, "10.0.0.2", "10.0.0.1", "TLS"),
    _packet(6, "10.0.0.1", "10.0.0.2", "HTTP"),
]


async def _open_topology_with_packets(page, packets=PLAY_PACKETS):
    await page.evaluate(
        """(response) => {
            const real = window.api;
            window.api = async (path, opts) => {
                if (path.includes('/conversations')) return response.conv;
                if (path.includes('/diagram-packets?')) return response.pkts;
                return real(path, opts);
            };
        }""",
        {"conv": CONVERSATIONS_PAYLOAD, "pkts": {"packets": packets, "total": len(packets)}},
    )
    await _open_viewer(page)
    await page.click("#btn-topology")
    await page.wait_for_selector("#topology-svg .diagram-node")


async def _play_to_end(page):
    await page.select_option("#topology-speed", "4")
    await page.click("#btn-topology-play")
    await page.wait_for_function(
        "() => document.getElementById('topology-playback-count').textContent.startsWith('Done')"
    )


async def test_speed_can_be_set_before_the_first_play(app_page):
    await _open_topology_with_packets(app_page)
    assert await app_page.is_enabled("#topology-speed")


async def test_a_finished_play_badges_each_host_and_rewinds(app_page):
    await _open_topology_with_packets(app_page)
    await _play_to_end(app_page)

    badges = await app_page.eval_on_selector_all(
        "#topology-svg .diagram-node",
        """gs => gs.map(g => [g.querySelector(':scope > text').textContent,
                              g.querySelector('.diagram-node-top text')?.textContent])""",
    )
    assert sorted(badges) == [["10.0.0.1", "TLS"], ["10.0.0.2", "TLS"]]
    # Progress is back at the start; the picture is not.
    assert await app_page.input_value("#topology-scrubber") == "0"
    assert await app_page.inner_text("#btn-topology-play") == "Play"

    # Playing again clears the badges until that play finishes too.
    await app_page.click("#btn-topology-play")
    assert await app_page.locator("#topology-svg .diagram-node-top").count() == 0


async def test_the_badge_lives_in_the_node_so_a_drag_carries_it(app_page):
    await _open_topology_with_packets(app_page)
    await _play_to_end(app_page)
    parent_is_node = await app_page.eval_on_selector_all(
        "#topology-svg .diagram-node-top", "els => els.every(b => b.parentElement.matches('.diagram-node'))"
    )
    assert parent_is_node


async def test_picking_a_protocol_narrows_the_next_play(app_page):
    await _open_topology_with_packets(app_page)
    await _play_to_end(app_page)

    await app_page.click("#topology-legend .diagram-legend-chip[data-key='DNS']")
    assert await app_page.get_attribute(
        "#topology-legend .diagram-legend-chip[data-key='DNS']", "aria-pressed") == "true"
    assert await app_page.get_attribute("#topology-legend .diagram-legend-chip[data-all]", "aria-pressed") == "false"
    assert await app_page.get_attribute("#topology-scrubber", "max") == "2"
    # A pick rewinds: no badges from the previous play survive it.
    assert await app_page.locator("#topology-svg .diagram-node-top").count() == 0

    await _play_to_end(app_page)
    assert "Done: 2 packets" in await app_page.inner_text("#topology-playback-count")
    tops = await app_page.eval_on_selector_all("#topology-svg .diagram-node-top text", "els => els.map(e => e.textContent)")
    assert tops == ["DNS", "DNS"]

    # A second pick adds to the first; "All" clears both.
    await app_page.click("#topology-legend .diagram-legend-chip[data-key='HTTP']")
    assert await app_page.get_attribute("#topology-scrubber", "max") == "3"
    await app_page.click("#topology-legend .diagram-legend-chip[data-all]")
    assert await app_page.get_attribute("#topology-scrubber", "max") == "6"


async def test_most_used_protocol_breaks_ties_by_overall_rank(app_page):
    top = await app_page.evaluate(
        """() => {
            const packets = [
                { source: 'a', destination: 'b', protocol: 'UDP' },
                { source: 'a', destination: 'c', protocol: 'TCP' },
                { source: 'c', destination: 'b', protocol: 'TCP' },
            ];
            const ranked = [['TCP', 2], ['UDP', 1]];
            return Object.fromEntries([...computeTopProtocols(packets, ranked)].map(([h, v]) => [h, v.proto]));
        }"""
    )
    # b saw one UDP and one TCP: TCP wins the tie as the more common overall.
    assert top == {"a": "TCP", "b": "TCP", "c": "TCP"}


async def test_stats_pane_shows_the_capture_and_collapses(app_page):
    await _open_topology_with_packets(app_page)
    body = await app_page.inner_text("#topology-stats-body")
    assert "Hosts" in body and "10.0.0.1" in body

    await _play_to_end(app_page)
    assert "TLS" in await app_page.inner_text("#topology-stats-body")

    before = await app_page.evaluate("() => document.getElementById('topology-svg').clientWidth")
    await app_page.click("#topology-stats > summary")
    await app_page.wait_for_function(
        "(w) => document.getElementById('topology-svg').clientWidth > w", arg=before
    )
    # The canvas follows the drawing area (on the resize observer's next
    # callback), so the marks keep lining up with the nodes.
    await app_page.wait_for_function(
        "() => document.getElementById('topology-svg').clientWidth"
        " === document.getElementById('topology-canvas').width"
    )


async def test_zoom_buttons_and_fit(app_page):
    await _open_topology_with_packets(app_page)
    fitted = await app_page.evaluate("() => topologyState.view.k")
    await app_page.click("#btn-topology-zoom-in")
    assert await app_page.evaluate("() => topologyState.view.k") > fitted
    await app_page.click("#btn-topology-zoom-out")
    await app_page.click("#btn-topology-zoom-out")
    assert await app_page.evaluate("() => topologyState.view.k") < fitted
    await app_page.click("#btn-topology-fit")
    assert abs(await app_page.evaluate("() => topologyState.view.k") - fitted) < 1e-9
    assert "%" in await app_page.inner_text("#topology-zoom-level")


async def test_wider_spacing_pushes_hosts_apart(app_page):
    await _open_topology_with_packets(app_page)
    dist = "() => { const [a, b] = topologyState.nodes; return Math.hypot(a.x - b.x, a.y - b.y); }"
    normal = await app_page.evaluate(dist)
    await app_page.select_option("#topology-spacing", "4")
    assert await app_page.evaluate(dist) > normal


async def test_no_two_hosts_overlap_after_layout(app_page):
    """Circles, labels and badge room: the layout separates what it draws,
    not just the centres."""
    payload = {
        "conversations": [{"a": "10.0.0.1", "b": f"10.0.0.{i}", "packets_a_to_b": 1, "bytes_a_to_b": 100 * i,
                           "packets_b_to_a": 1, "bytes_b_to_a": 100} for i in range(2, 30)],
        "endpoints": [{"address": f"10.0.0.{i}", "packets": 2, "bytes": 100 * i + 100} for i in range(1, 30)],
    }
    await _stub_api(app_page, "/conversations", payload)
    await _open_viewer(app_page)
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-svg .diagram-node")
    overlaps = await app_page.evaluate("""() => {
        // At the glyph scale the fitted view actually draws them at.
        const boxes = topologyState.nodes.map((n) => nodeBox(n, glyphScale()));
        let n = 0;
        for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
            const A = boxes[i], B = boxes[j];
            if (Math.min(A.right, B.right) > Math.max(A.left, B.left) &&
                Math.min(A.bottom, B.bottom) > Math.max(A.top, B.top)) n++;
        }
        return n;
    }""")
    assert overlaps == 0


async def test_full_screen_toggles_and_clears_on_close(app_page):
    await _open_topology_with_packets(app_page)
    await app_page.click("#btn-topology-fullscreen")
    assert await app_page.get_attribute("#btn-topology-fullscreen", "aria-pressed") == "true"
    assert await app_page.evaluate("() => document.getElementById('topology-dialog').classList.contains('is-fullscreen')")
    await app_page.evaluate("() => document.getElementById('topology-dialog').close()")
    # "close" is dispatched a task later, not inside close() itself.
    await app_page.wait_for_function(
        "() => !document.getElementById('topology-dialog').classList.contains('is-fullscreen')")
    assert await app_page.get_attribute("#btn-topology-fullscreen", "aria-pressed") == "false"


async def test_title_names_the_capture_and_the_open_view(app_page):
    await _stub_api(app_page, "/conversations", CONVERSATIONS_PAYLOAD)
    await _open_viewer(app_page)
    await app_page.evaluate("""() => {
        captures = [{ id: 'cap-1', name: 'home <lan>.pcap' }];
        savedViews = [{ id: 'v1', name: 'dns only', display_filter: 'dns' }];
        activeViewId = ALL_PACKETS_VIEW;
    }""")
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-dialog[open]")
    assert await app_page.inner_text("#topology-context") == "home <lan>.pcap"
    await app_page.evaluate("() => document.getElementById('topology-dialog').close()")

    await app_page.evaluate("() => { activeViewId = 'v1'; }")
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-dialog[open]")
    assert await app_page.inner_text("#topology-context .diagram-context-view") == "View: dns only"


def _iface_packet(number, source, destination, interface):
    packet = _packet(number, source, destination, "TCP")
    packet["interface"] = interface
    return packet


async def test_an_any_capture_labels_each_host_with_its_interfaces(app_page):
    """Fetched as the dialog opens -- no Play needed -- and reused by Play."""
    packets = [
        _iface_packet(1, "10.0.0.1", "10.0.0.2", "eth0"),
        _iface_packet(2, "10.0.0.2", "10.0.0.1", "wlan0"),
        _iface_packet(3, "10.0.0.1", "10.0.0.2", "eth0"),
    ]
    await app_page.evaluate(
        """(response) => {
            window.__packetFetches = 0;
            const real = window.api;
            window.api = async (path, opts) => {
                if (path.includes('/conversations')) return response.conv;
                if (path.includes('/diagram-packets?')) { window.__packetFetches++; return response.pkts; }
                return real(path, opts);
            };
        }""",
        {"conv": CONVERSATIONS_PAYLOAD, "pkts": {"packets": packets, "total": len(packets)}},
    )
    await _open_viewer(app_page)
    await app_page.evaluate("() => { captures = [{ id: 'cap-1', name: 'x', interface: 'any' }]; }")
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-svg .diagram-node-iface")

    labels = await app_page.eval_on_selector_all(
        "#topology-svg .diagram-node-iface", "els => els.map(e => e.textContent)")
    assert labels == ["eth0 · wlan0", "eth0 · wlan0"]
    await _play_to_end(app_page)
    assert await app_page.evaluate("() => window.__packetFetches") == 1


async def test_a_capture_without_interfaces_draws_no_interface_labels(app_page):
    await _open_topology_with_packets(app_page)
    await _play_to_end(app_page)
    assert await app_page.locator("#topology-svg .diagram-node-iface").count() == 0


async def test_every_interface_a_host_was_seen_on_is_collected(app_page):
    text = await app_page.evaluate("""() => {
        const per = computeNodeInterfaces([
            { source: 'a', destination: 'b', interface: 'eth0' },
            { source: 'a', destination: 'c', interface: 'wlan0' },
            { source: 'a', destination: 'd', interface: 'br-lan' },
        ]);
        return [...per.get('a')].sort();
    }""")
    assert text == ["br-lan", "eth0", "wlan0"]


# --- "New window": the diagram as a page of its own --------------------------


def _upload_sample(api_client) -> str:
    from scripts.preview_pcap import build

    response = api_client.post(
        "/api/captures/upload", params={"filename": "window-test.pcap"}, content=build(sessions=20),
        headers={"Content-Type": "application/octet-stream"},
    )
    response.raise_for_status()
    return response.json()["id"]


async def test_new_window_url_carries_capture_filter_and_spacing(app_page):
    await _stub_api(app_page, "/conversations", CONVERSATIONS_PAYLOAD)
    await _open_viewer(app_page)
    await app_page.fill("#display-filter", "dns")
    await app_page.press("#display-filter", "Escape")  # close the suggestions over the toolbar
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-dialog[open]")
    await app_page.select_option("#topology-spacing", "2.5")
    url = await app_page.evaluate("() => diagramWindowUrl()")
    assert "#traffic-diagram?" in url
    assert "capture=cap-1" in url and "filter=dns" in url and "spacing=2.5" in url


async def _second_window(app_page, path):
    """A fresh load in the same signed-in browser, as window.open gives. A
    goto on the existing page would only change its hash, not reload it."""
    window = await app_page.context.new_page()
    errors = []
    window.on("pageerror", lambda exc: errors.append(str(exc)))
    await window.goto(path)
    return window, errors


async def test_the_diagram_window_shows_only_the_diagram(app_page, api_client):
    capture_id = _upload_sample(api_client)
    window, errors = await _second_window(app_page, f"/#traffic-diagram?capture={capture_id}&spacing=1.6&names=0")
    await window.wait_for_selector("#topology-svg .diagram-node")

    assert await window.evaluate("() => document.body.classList.contains('diagram-window')")
    assert await window.evaluate(
        "() => document.getElementById('topology-dialog').classList.contains('is-fullscreen')")
    assert await window.input_value("#topology-spacing") == "1.6"
    assert await window.inner_text("#topology-context") == "window-test.pcap"
    assert await window.is_hidden("#btn-topology-new-window")
    assert errors == []


async def test_a_diagram_window_for_an_unknown_capture_falls_back_to_the_app(app_page):
    """The capture id in the hash is only used if it is one of the user's own."""
    window, _ = await _second_window(app_page, "/#traffic-diagram?capture=..%2F..%2Fapi%2Fadmin%2Fusers")
    await window.wait_for_function("() => location.hash === ''")
    assert await window.locator("#topology-dialog[open]").count() == 0
    assert not await window.evaluate("() => document.body.classList.contains('diagram-window')")


async def test_every_protocol_gets_its_own_chip(app_page):
    """No "Other" in the Traffic Diagram's picker: past the eighth, protocols
    share the neutral mark but each is still pickable on its own."""
    protocols = ["TCP", "UDP", "DNS", "TLS", "HTTP", "ICMP", "ARP", "NTP", "SNMP", "SSH"]
    packets = [_packet(i + 1, "10.0.0.1", "10.0.0.2", proto) for i, proto in enumerate(protocols)]
    await _open_topology_with_packets(app_page, packets)
    await app_page.click("#btn-topology-play")
    await app_page.wait_for_selector("#topology-legend .diagram-legend-chip:not([data-key^='problem:'])[data-key]")

    chips = await app_page.eval_on_selector_all(
        "#topology-legend .diagram-legend-chip:not([data-key^='problem:'])[data-key]", "els => els.map(e => e.dataset.key)")
    assert sorted(chips) == sorted(protocols)
    assert await app_page.locator("#topology-legend [data-other]").count() == 0

    await app_page.click("#topology-legend .diagram-legend-chip[data-key='SSH']")
    await app_page.click("#topology-legend .diagram-legend-chip[data-key='SNMP']")
    assert await app_page.get_attribute("#topology-scrubber", "max") == "2"
    assert "one or more" in await app_page.inner_text("#topology-legend .diagram-legend-hint")


async def test_fifteen_protocols_each_get_a_colored_mark_of_their_own(app_page):
    protocols = [f"P{i:02d}" for i in range(16)]
    packets, n = [], 0
    for rank, proto in enumerate(protocols):  # descending counts fix the order
        for _ in range(len(protocols) - rank):
            n += 1
            packets.append(_packet(n, "10.0.0.1", "10.0.0.2", proto))
    await _open_topology_with_packets(app_page, packets)
    await app_page.click("#btn-topology-play")
    await app_page.wait_for_selector("#topology-legend .diagram-legend-chip:not([data-key^='problem:'])[data-key]")

    marks = await app_page.eval_on_selector_all(
        "#topology-legend .diagram-legend-chip:not([data-key^='problem:'])[data-key] svg",
        """els => els.map(svg => {
            const shape = svg.lastElementChild;
            const kind = shape.tagName === 'circle' && shape.getAttribute('fill') === 'none' ? 'ring'
                : shape.tagName === 'path' ? shape.getAttribute('d') : shape.tagName;
            return svg.getAttribute('fill') + '|' + kind;
        })""",
    )
    assert len(marks) == 16
    first15 = marks[:15]
    assert len(set(first15)) == 15, first15
    assert not any("diagram-other" in m for m in first15)
    assert "diagram-other" in marks[15], "only past fifteen does a protocol go neutral"


THREE_HOSTS = {
    "conversations": [
        {"a": "10.0.0.1", "b": "10.0.0.2", "packets_a_to_b": 1, "bytes_a_to_b": 100,
         "packets_b_to_a": 1, "bytes_b_to_a": 100},
        {"a": "10.0.0.1", "b": "10.0.0.3", "packets_a_to_b": 1, "bytes_a_to_b": 100,
         "packets_b_to_a": 0, "bytes_b_to_a": 0},
    ],
    "endpoints": [{"address": f"10.0.0.{i}", "packets": 1, "bytes": 100} for i in (1, 2, 3)],
}


async def test_picking_protocols_hides_hosts_and_links_they_never_touched(app_page):
    packets = [
        _packet(1, "10.0.0.1", "10.0.0.2", "DNS"),
        _packet(2, "10.0.0.2", "10.0.0.1", "DNS"),
        _packet(3, "10.0.0.1", "10.0.0.3", "TLS"),
    ]
    await app_page.evaluate(
        """(r) => { const real = window.api; window.api = async (path, opts) =>
            path.includes('/conversations') ? r.conv : path.includes('/diagram-packets?') ? r.pkts : real(path, opts); }""",
        {"conv": THREE_HOSTS, "pkts": {"packets": packets, "total": 3}},
    )
    await _open_viewer(app_page)
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-svg .diagram-node")
    await app_page.click("#btn-topology-play")
    await app_page.wait_for_selector("#topology-legend .diagram-legend-chip[data-key='DNS']")

    visible = "() => [...document.querySelectorAll('#topology-svg .diagram-node:not(.is-hidden) > text')].map(t => t.firstChild.textContent).sort()"
    links = "() => document.querySelectorAll('#topology-svg .diagram-edge:not(.is-hidden)').length"
    await app_page.click("#topology-legend .diagram-legend-chip[data-key='DNS']")
    assert await app_page.evaluate(visible) == ["10.0.0.1", "10.0.0.2"]
    assert await app_page.evaluate(links) == 1

    await app_page.click("#topology-legend .diagram-legend-chip[data-all]")
    assert await app_page.evaluate(visible) == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    assert await app_page.evaluate(links) == 2


async def test_resolve_names_can_be_switched_from_the_diagram(app_page):
    await app_page.evaluate(
        """(response) => {
            window.__calls = [];
            const real = window.api;
            window.api = async (path, opts) => {
                window.__calls.push(path);
                if (path.includes('/conversations')) return response;
                return real(path, opts);
            };
        }""",
        CONVERSATIONS_PAYLOAD,
    )
    await _open_viewer(app_page)
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-svg .diagram-node")
    assert not await app_page.is_checked("#topology-resolve")

    await app_page.check("#topology-resolve")
    await app_page.wait_for_function(
        "() => window.__calls.some(c => c.includes('/conversations') && c.includes('resolve_names=true'))")
    # One setting: the page's own toggle follows.
    assert await app_page.evaluate("() => document.getElementById('resolve-names').checked")
    assert await app_page.is_checked("#topology-resolve")


async def test_protocols_are_in_the_stats_and_legend_before_any_play(app_page):
    await _open_topology_with_packets(app_page)
    await app_page.wait_for_selector("#topology-legend .diagram-legend-chip[data-key='TLS']")
    stats = await app_page.inner_text("#topology-stats-body")
    assert "TLS" in stats and "DNS" in stats and "HTTP" in stats
    assert await app_page.inner_text("#btn-topology-play") == "Play"


PROBLEM_PACKETS = [
    _packet(1, "10.0.0.1", "10.0.0.2", "TCP", "51000 → 8080 [SYN] Seq=0"),
    _packet(2, "10.0.0.2", "10.0.0.1", "TCP", "8080 → 51000 [RST, ACK] Seq=1 Ack=1"),
    _packet(3, "10.0.0.1", "10.0.0.2", "IPv4", "Fragmented IP protocol (proto=UDP 17, off=0, ID=4d31)"),
    _packet(4, "10.0.0.2", "10.0.0.1", "TLS", "[TCP Retransmission] 443 → 51453 [PSH, ACK]"),
    _packet(5, "10.0.0.1", "10.0.0.2", "DNS", "Standard query 0x4321 A example.com"),
]


async def test_problems_are_counted_badged_and_pickable(app_page):
    """Each problem kind is a chip of its own, in a Problems group."""
    await _open_topology_with_packets(app_page, PROBLEM_PACKETS)
    await app_page.wait_for_selector("#topology-legend .diagram-legend-chip[data-key='problem:reset']")

    group = await app_page.inner_text("#topology-legend .diagram-chip-group--problems")
    assert "Resets (1)" in group and "IP fragments (1)" in group and "Retransmissions / lost (1)" in group
    stats = await app_page.inner_text("#topology-stats-body")
    assert "Resets" in stats and "IP fragments" in stats and "Retransmissions" in stats
    assert await app_page.text_content("#topology-svg .diagram-problem-badge text") == "⚠3"

    # One kind on its own plays only those packets.
    await app_page.click("#topology-legend .diagram-legend-chip[data-key='problem:reset']")
    assert await app_page.get_attribute("#topology-scrubber", "max") == "1"
    assert await app_page.text_content("#topology-svg .diagram-problem-badge text") == "⚠1"
    # The group's name picks every kind in it.
    await app_page.click("#topology-legend .diagram-chip-group--problems .diagram-chip-group-label")
    assert await app_page.get_attribute("#topology-scrubber", "max") == "3"
    # Alongside a protocol, the two add up.
    await app_page.click("#topology-legend .diagram-legend-chip[data-key='DNS']")
    assert await app_page.get_attribute("#topology-scrubber", "max") == "4"


async def test_unpicking_problems_takes_their_icons_away(app_page):
    """A play of just DNS shows no problem badges -- the icons follow the chips."""
    await _open_topology_with_packets(app_page, PROBLEM_PACKETS)
    await app_page.wait_for_selector("#topology-svg .diagram-problem-badge")
    await app_page.click("#topology-legend .diagram-legend-chip[data-key='DNS']")
    assert await app_page.locator("#topology-svg .diagram-problem-badge").count() == 0
    # Unpicked chips step back while something is picked.
    assert await app_page.locator("#topology-legend.has-picks").count() == 1
    await app_page.click("#topology-legend .diagram-legend-chip[data-all]")
    assert await app_page.locator("#topology-svg .diagram-problem-badge").count() == 1


async def test_a_problem_row_filters_the_packet_list(app_page):
    await _open_topology_with_packets(app_page, PROBLEM_PACKETS)
    await app_page.wait_for_selector("#topology-stats-body [data-problem='reset']")
    await app_page.click("#topology-stats-body [data-problem='reset']")
    assert await app_page.input_value("#display-filter") == "tcp.flags.reset == 1"
    assert await app_page.locator("#topology-dialog[open]").count() == 1


async def test_host_search_highlights_matches_and_steps_through_them(app_page):
    await app_page.evaluate(
        """(r) => { const real = window.api; window.api = async (path, opts) =>
            path.includes('/conversations') ? r : path.includes('/diagram-packets?') ? { packets: [], total: 0 } : real(path, opts); }""",
        THREE_HOSTS,
    )
    await _open_viewer(app_page)
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-svg .diagram-node")
    assert await app_page.is_visible("#topology-search")

    await app_page.fill("#topology-search", "0.0.2")
    assert await app_page.locator("#topology-svg .diagram-node.is-match").count() == 1
    assert await app_page.locator("#topology-svg .diagram-node.is-dimmed").count() == 2
    await app_page.press("#topology-search", "Enter")
    assert "1 of 1: 10.0.0.2" in await app_page.inner_text("#topology-search-count")

    await app_page.fill("#topology-search", "nothing-like-this")
    assert await app_page.inner_text("#topology-search-count") == "No host matches"
    await app_page.press("#topology-search", "Escape")
    assert await app_page.input_value("#topology-search") == ""
    assert await app_page.locator("#topology-svg .is-dimmed").count() == 0
    assert await app_page.locator("#topology-dialog[open]").count() == 1


# --- captures above the Sequence Diagram's 10,000 packets ---------------------------------------------


async def test_traffic_diagram_plays_a_capture_past_the_sequence_cap(app_page):
    # 12,000 packets: over the Sequence Diagram's 10,000, under the server's
    # ceiling (the route reports it as "cap"). The Traffic Diagram draws it.
    packets = [_packet(i, "10.0.0.1", "10.0.0.2") for i in range(1, 12001)]
    await app_page.evaluate(
        """(r) => { const real = window.api; window.api = async (path, opts) =>
            path.includes('/conversations') ? r.conv
            : path.includes('/diagram-packets?') ? r.pkts : real(path, opts); }""",
        {"conv": CONVERSATIONS_PAYLOAD, "pkts": {"packets": packets, "total": 12000, "cap": 100000}},
    )
    await _open_viewer(app_page)
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-svg .diagram-node")
    await app_page.click("#btn-topology-play")
    await app_page.wait_for_function(
        "() => document.getElementById('topology-playback-count').textContent.endsWith('/ 12,000')"
    )
    assert await app_page.is_hidden("#topology-cap-warning")


async def test_traffic_diagram_warning_reports_the_servers_cap(app_page):
    await app_page.evaluate(
        """(r) => { const real = window.api; window.api = async (path, opts) =>
            path.includes('/conversations') ? r
            : path.includes('/diagram-packets?') ? { packets: [], total: 150000, cap: 100000 }
            : real(path, opts); }""",
        CONVERSATIONS_PAYLOAD,
    )
    await _open_viewer(app_page)
    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-svg .diagram-node")
    await app_page.click("#btn-topology-play")
    await app_page.wait_for_selector("#topology-cap-warning:not([hidden])")
    text = await app_page.inner_text("#topology-cap-warning")
    assert "150,000 packets" in text and "100,000" in text


async def test_sequence_diagram_asks_for_its_own_cap(app_page):
    await app_page.evaluate(
        """() => { window.__calls = []; const real = window.api; window.api = async (path, opts) => {
            window.__calls.push(path);
            return path.includes('/diagram-packets?') ? { packets: [], total: 0, cap: 10000 } : real(path, opts); }; }"""
    )
    await _open_viewer(app_page)
    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")
    await app_page.wait_for_function("() => window.__calls.some((c) => c.includes('/diagram-packets?'))")
    calls = await app_page.evaluate("() => window.__calls")
    assert any("/diagram-packets?" in c and "limit=10000" in c for c in calls)


async def test_edge_heat_carried_forward_matches_a_recount(app_page):
    # edgeHeatAt reuses the last frame's counts; forwards, backwards and
    # forwards again it must agree with computeEdgeHeat counting from zero.
    same = await app_page.evaluate(
        """() => {
            const hosts = ['a', 'b', 'c'];
            const packets = Array.from({ length: 200 }, (_, i) =>
                ({ source: hosts[i % 3], destination: hosts[(i * 7 + 1) % 3] }));
            const pb = { packets };
            const plain = (m) => JSON.stringify([...m].sort());
            return [150, 40, 199, 0, 120].every((idx) =>
                plain(edgeHeatAt(pb, idx)) === plain(computeEdgeHeat(packets, idx)));
        }"""
    )
    assert same


async def test_each_diagram_always_asks_for_its_own_cap(app_page):
    """The Capture tab's checkboxes no longer switch the drawing caps off:
    unticked (the default), each diagram still asks for no more than it draws."""
    await app_page.evaluate(
        """(r) => { window.__calls = []; const real = window.api; window.api = async (path, opts) => {
            window.__calls.push(path);
            return path.includes('/conversations') ? r
                : path.includes('/diagram-packets?') ? { packets: [], total: 0, cap: 1 } : real(path, opts); }; }""",
        CONVERSATIONS_PAYLOAD,
    )
    assert not await app_page.is_checked("#topology-cap-enabled")
    assert not await app_page.is_checked("#sequence-cap-enabled")
    await _open_viewer(app_page)
    await app_page.click("#btn-topology")
    await app_page.wait_for_function(
        "() => window.__calls.some((c) => c.includes('/diagram-packets?') && c.includes('limit=100000'))"
    )
    await app_page.evaluate("() => $('topology-dialog').close()")
    await app_page.click("#btn-sequence")
    await app_page.wait_for_function(
        "() => window.__calls.some((c) => c.includes('/diagram-packets?') && c.includes('limit=10000'))"
    )


async def test_the_cap_checkboxes_show_their_max_and_have_tooltips(app_page):
    for sel, shown in (("label:has(#topology-cap-enabled)", "100,000"), ("label:has(#sequence-cap-enabled)", "10,000")):
        assert shown in await app_page.inner_text(sel)
        assert "ticked" in (await app_page.get_attribute(sel, "title")).lower()


# --- names, zones, selection, saved layouts ----------------------------------


NAMED = {
    "conversations": [
        {"a": "10.254.253.113", "b": "52.9.185.162", "packets_a_to_b": 3, "bytes_a_to_b": 300,
         "packets_b_to_a": 3, "bytes_b_to_a": 300},
        {"a": "10.254.253.113", "b": "10.42.0.7", "packets_a_to_b": 2, "bytes_a_to_b": 200,
         "packets_b_to_a": 2, "bytes_b_to_a": 200},
    ],
    "endpoints": [
        {"address": "10.254.253.113", "name": "", "packets": 10, "bytes": 1000},
        {"address": "52.9.185.162", "name": "ec2-52-9-185-162.us-west-1.compute.amazonaws.com",
         "packets": 6, "bytes": 600},
        {"address": "10.42.0.7", "name": "", "packets": 4, "bytes": 400},
    ],
}


async def _open_named(page, packets=None):
    packets = packets or []
    await page.evaluate(
        """(r) => { const real = window.api; window.api = async (path, opts) =>
            path.includes('/conversations') ? r.conv : path.includes('/diagram-packets?') ? r.pkts : real(path, opts); }""",
        {"conv": NAMED, "pkts": {"packets": packets, "total": len(packets), "names": {}}},
    )
    await _open_viewer(page)
    await page.click("#btn-topology")
    await page.wait_for_selector("#topology-svg .diagram-node")


async def test_a_resolved_host_shows_its_name_over_its_address_and_filters_by_address(app_page):
    """The regression: with names on, a click built ip.addr == "ec2-..." and
    tshark refused it. The node is keyed by address; the name is a label."""
    await _open_named(app_page)
    node = app_page.locator("#topology-svg .diagram-node[data-id='52.9.185.162']")
    assert "ec2-52-9-185-162" in await node.locator(".diagram-node-name").text_content()
    assert await node.locator(".diagram-node-ip").text_content() == "52.9.185.162"
    await node.locator("circle").click()
    assert await app_page.input_value("#display-filter") == "ip.addr == 52.9.185.162"


async def test_selecting_a_host_lights_up_everything_it_talks_to(app_page):
    await _open_named(app_page)
    await app_page.click("#topology-svg .diagram-node[data-id='52.9.185.162'] circle")
    assert await app_page.locator("#topology-svg .diagram-node.is-selected").count() == 1
    neighbor = "#topology-svg .diagram-node[data-id='10.254.253.113']"
    assert "is-neighbor" in await app_page.get_attribute(neighbor, "class")
    assert "is-faded" in await app_page.get_attribute("#topology-svg .diagram-node[data-id='10.42.0.7']", "class")
    assert await app_page.locator("#topology-svg .diagram-edge.is-active").count() == 1


async def test_links_are_colored_by_zone_and_the_internet_sits_on_top(app_page):
    await _open_named(app_page)
    classes = await app_page.eval_on_selector_all(
        "#topology-svg .diagram-edge", "els => els.map(e => e.getAttribute('class'))")
    assert any("zone-internet" in c for c in classes)
    # 10.42.0.0/16: a k3s pod, with no interface on record to say otherwise.
    assert "zone-box" in await app_page.get_attribute("#topology-svg .diagram-node[data-id='10.42.0.7']", "class")
    ys = await app_page.evaluate("() => Object.fromEntries(topologyState.nodes.map(n => [n.id, n.y]))")
    assert ys["52.9.185.162"] < min(ys["10.254.253.113"], ys["10.42.0.7"])


async def test_the_box_address_is_found_from_its_physical_interface(app_page):
    packets = [
        {**_packet(i, "10.254.253.113", "52.9.185.162"), "interface": "ens18"} for i in range(1, 12)
    ] + [{**_packet(20, "10.42.0.7", "10.254.253.113"), "interface": "cni0"}]
    await _open_named(app_page, packets)
    await app_page.wait_for_selector("#topology-svg .diagram-node.is-egress")
    assert await app_page.get_attribute("#topology-svg .diagram-node.is-egress", "data-id") == "10.254.253.113"
    assert "zone-box" in await app_page.get_attribute("#topology-svg .diagram-node[data-id='10.42.0.7']", "class")
    assert "likely" in await app_page.inner_text("#topology-stats-body")


async def test_a_layout_saves_positions_and_picks_against_the_capture(app_page):
    await app_page.evaluate("""() => {
        window.__saved = null;
        const real = window.api;
        window.api = async (path, opts) => {
            if (path.includes('/diagram-views') && opts && opts.method === 'POST') {
                window.__saved = JSON.parse(opts.body);
                return { id: 'v1', capture_id: 'cap-1', name: window.__saved.name, state: window.__saved.state };
            }
            if (path.includes('/diagram-views')) return window.__saved
                ? [{ id: 'v1', capture_id: 'cap-1', name: window.__saved.name, state: window.__saved.state }] : [];
            return real(path, opts);
        };
        window.prompt = () => 'my layout';
    }""")
    await _open_named(app_page, [_packet(1, "10.254.253.113", "52.9.185.162", "TLS")])
    await app_page.wait_for_selector("#topology-legend .diagram-legend-chip[data-key='TLS']")
    await app_page.click("#topology-legend .diagram-legend-chip[data-key='TLS']")
    await app_page.evaluate("() => { const n = topologyState.byId.get('10.42.0.7'); n.x = 123; n.y = 45; }")
    await app_page.click("#btn-topology-layout-save")
    await app_page.wait_for_function("() => window.__saved !== null")
    saved = await app_page.evaluate("() => window.__saved")
    assert saved["name"] == "my layout"
    assert saved["state"]["positions"]["10.42.0.7"] == {"x": 123, "y": 45}
    assert saved["state"]["selected"] == ["TLS"]

    # Opening it again puts the host back where it was saved.
    await app_page.evaluate("() => { const n = topologyState.byId.get('10.42.0.7'); n.x = 0; n.y = 0; }")
    await app_page.wait_for_selector("#topology-layout-select option[value='v1']", state="attached")
    await app_page.select_option("#topology-layout-select", "v1")
    await app_page.wait_for_function(
        "() => topologyState && topologyState.byId.get('10.42.0.7')?.x === 123 && topologyState.restored")


async def test_the_diagram_header_names_the_capture_it_draws(app_page):
    await app_page.evaluate("""() => { captures = [{ id: 'cap-1', name: 'slow logons', interface: 'any',
        bpf_filter: 'not arp', packet_count: 1234, started_at: '2026-09-18T10:00:00+00:00',
        server_label: 'box-1', status: 'completed' }]; }""")
    await _open_named(app_page)
    details = await app_page.inner_text("#topology-capture-details")
    assert "box-1" in details and "not arp" in details and "1,234" in details


# --- the Capture tab: optimize for diagrams, NOT in the filter library -----


async def _capture_panel(page):
    await page.evaluate("() => activatePanel('capture')")


async def test_ticking_a_diagram_fits_the_capture_to_it(app_page):
    await _capture_panel(app_page)
    # Unticked by default.
    assert not await app_page.is_checked("#topology-cap-enabled")
    assert not await app_page.is_checked("#sequence-cap-enabled")
    assert await app_page.is_hidden("#optimize-panel")
    await app_page.fill("#cap-bpf", "host 10.0.0.1")
    await app_page.check("#sequence-cap-enabled")
    assert await app_page.input_value("#cap-count") == "10000"
    assert await app_page.input_value("#cap-snaplen") == "256"
    bpf = await app_page.input_value("#cap-bpf")
    assert bpf.startswith("(host 10.0.0.1) and not (arp or stp")
    # Changing the exclusions rewrites our own clause, not a second copy of it.
    await app_page.uncheck("#optimize-exclusions input[value='arp']")
    bpf = await app_page.input_value("#cap-bpf")
    assert bpf.startswith("(host 10.0.0.1) and not (stp") and bpf.count("and not") == 1


async def test_a_library_row_can_be_excluded_with_not(app_page):
    await _capture_panel(app_page)
    await app_page.evaluate("() => { document.getElementById('filter-library-details').open = true; }")
    await app_page.fill("#cap-bpf", "")
    await app_page.evaluate("() => onBpfFilterChanged()")
    first = app_page.locator("#filter-library [data-action='exclude-library-filter']").first
    expr = await first.get_attribute("data-id")
    await first.click()
    assert await app_page.input_value("#cap-bpf") == f"not ({expr})"


async def test_the_box_address_is_what_only_ever_goes_out(app_page):
    """On an "any" capture the kernel's direction decides: a forwarded packet
    arrives before it leaves, the box's own only ever leave."""
    def pkt(n, src, dst, iface, direction):
        return {**_packet(n, src, dst), "interface": iface, "direction": direction}
    packets = [pkt(i, "10.254.253.113", "52.9.185.162", "ens18", "out") for i in range(1, 5)]
    # A pod's packet: in on cni0 -- busier than the node, but never "out" alone.
    packets += [pkt(10 + i, "10.42.0.7", "52.9.185.162", "cni0", "in") for i in range(20)]
    await _open_named(app_page, packets)
    await app_page.wait_for_selector("#topology-svg .diagram-node.is-egress")
    assert await app_page.locator("#topology-svg .diagram-node.is-egress").count() == 1
    assert await app_page.get_attribute("#topology-svg .diagram-node.is-egress", "data-id") == "10.254.253.113"


async def test_link_colors_can_be_changed_and_reset(app_page):
    await _open_named(app_page)
    await app_page.evaluate("""() => { const i = document.getElementById('zone-color-internet');
        i.value = '#ff00aa'; i.dispatchEvent(new Event('input', { bubbles: true })); }""")
    edge = "#topology-svg .diagram-edge.zone-internet"
    assert await app_page.evaluate(f"() => getComputedStyle(document.querySelector('{edge}')).stroke") == "rgb(255, 0, 170)"
    assert await app_page.is_visible("#btn-zone-colors-reset")
    await app_page.click("#btn-zone-colors-reset")
    assert await app_page.evaluate(f"() => getComputedStyle(document.querySelector('{edge}')).stroke") != "rgb(255, 0, 170)"


async def test_the_interfaces_dialog_suggests_subnets_and_saves_the_named_ones(app_page):
    await app_page.evaluate("""(conv) => {
        window.__put = null;
        captures = [{ id: 'cap-1', name: 'uploaded', interface: '', status: 'completed', subnet_map: [] }];
        const real = window.api;
        window.api = async (path, opts) => {
            if (path.includes('/conversations')) return conv;
            if (path.includes('/subnet-map')) { window.__put = JSON.parse(opts.body); return {}; }
            if (path === '/api/captures') return captures;
            return real(path, opts);
        };
    }""", NAMED)
    await app_page.evaluate("() => openSubnetMapDialog('cap-1')")
    await app_page.wait_for_selector("#subnet-map-rows .subnet-cidr")
    cidrs = await app_page.eval_on_selector_all("#subnet-map-rows .subnet-cidr", "els => els.map(e => e.value)")
    # Private /24s from the capture; the public address is not offered.
    assert set(cidrs) == {"10.254.253.0/24", "10.42.0.0/24"}
    await app_page.locator("#subnet-map-rows .subnet-name").nth(cidrs.index("10.42.0.0/24")).fill("cni0")
    await app_page.click("#btn-subnet-map-save")
    await app_page.wait_for_function("() => window.__put !== null")
    # Only the named row is saved.
    assert await app_page.evaluate("() => window.__put") == {"mappings": [{"cidr": "10.42.0.0/24", "name": "cni0"}]}
    assert await app_page.locator("#subnet-map-dialog[open]").count() == 0


async def test_protocols_and_stats_both_fold_away(app_page):
    await _open_named(app_page)
    for pane in ("#topology-chips", "#topology-stats"):
        assert await app_page.evaluate(f"() => document.querySelector('{pane}').open")
        await app_page.click(f"{pane} > summary")
        assert not await app_page.evaluate(f"() => document.querySelector('{pane}').open")
    # Remembered: the next open of the diagram keeps them folded.
    assert await app_page.evaluate("() => localStorage.getItem('pcap.topologyChipsOpen')") == "0"
    await app_page.evaluate("() => { localStorage.removeItem('pcap.topologyChipsOpen'); localStorage.removeItem('pcap.topologyStatsOpen'); }")


async def _start_capture_request(page, count_value):
    """Press Start capture with the form as it stands; the request body it sends."""
    await page.evaluate("""(count) => {
        window.__started = null;
        const sel = document.getElementById('cap-server');
        if (!sel.querySelector('option[value="srv-1"]')) sel.append(new Option('box-1', 'srv-1'));
        sel.value = 'srv-1';
        document.getElementById('cap-name').value = 'limit check';
        document.getElementById('cap-count').value = count;
        window.confirm = () => true;
        confirmBpfFilter = async () => true;
        const real = window.api;
        window.api = async (path, opts) => {
            if (path === '/api/captures' && opts && opts.method === 'POST') { window.__started = JSON.parse(opts.body); return {}; }
            return real(path, opts);
        };
    }""", count_value)
    await page.evaluate("() => startCapture()")
    await page.wait_for_function("() => window.__started !== null")
    return await page.evaluate("() => window.__started")


async def test_a_ticked_diagram_polices_the_capture_limit(app_page):
    await _capture_panel(app_page)
    await app_page.check("#sequence-cap-enabled")
    # Blank Max packets: exactly the diagram's cap, not the server maximum.
    assert (await _start_capture_request(app_page, ""))["count"] == 10000
    # More than it can draw: held to the cap (the confirm is answered OK).
    assert (await _start_capture_request(app_page, "50000"))["count"] == 10000
    # Less is left alone.
    assert (await _start_capture_request(app_page, "800"))["count"] == 800
    # One per capture: ticking Traffic unticks Sequence, and its cap applies.
    await app_page.fill("#cap-count", "")
    await app_page.check("#topology-cap-enabled")
    assert not await app_page.is_checked("#sequence-cap-enabled")
    assert await app_page.input_value("#cap-count") == "100000"
    assert (await _start_capture_request(app_page, ""))["count"] == 100000
    # Neither ticked: no limit is added.
    await app_page.uncheck("#topology-cap-enabled")
    assert "count" not in await _start_capture_request(app_page, "")


async def test_every_problem_kind_is_colored_in_the_packet_list(app_page):
    """The list's Problem color follows the diagram's own problem kinds, so a
    fragment is colored like a retransmission -- it used to look normal."""
    classes = await app_page.evaluate("""() => [
        'Fragmented IP protocol (proto=UDP 17, off=0, ID=4d31)',
        'IPv6 fragment (off=0 more=y ident=0x1)',
        '[TCP Retransmission] 443 → 51453 [PSH, ACK]',
        '[TCP ZeroWindow] 443 → 51453 [ACK]',
        'Destination unreachable (Port unreachable)',
        '[Malformed Packet]',
        'Standard query 0x4321 A example.com',
    ].map((info) => packetClass({ protocol: 'IPV4', info }))""")
    assert classes[:6] == ["pkt-bad"] * 6
    assert classes[6] != "pkt-bad"


async def test_the_interface_mapping_is_entered_before_the_upload_and_sent_with_it(app_page):
    await _capture_panel(app_page)
    await app_page.evaluate("""() => {
        window.__upload = null;
        const real = window.api;
        window.api = async (path, opts) => {
            if (path.startsWith('/api/captures/upload')) {
                window.__upload = path;
                return { id: 'up-1', packet_count: 3, subnet_map: [{ cidr: '192.168.1.0/24', name: 'eth0' }] };
            }
            if (path === '/api/captures') return [];
            return real(path, opts);
        };
    }""")
    await app_page.click("#btn-upload-toggle")
    await app_page.set_input_files("#upload-file", files=[
        {"name": "multi.pcapng", "mimeType": "application/octet-stream", "buffer": b"\x0a\x0d\x0d\x0a" + b"\x00" * 60}])
    await app_page.check("#upload-multi-iface")
    # The dialog opens now, before anything is sent.
    await app_page.wait_for_selector("#subnet-map-dialog[open]")
    assert await app_page.inner_text("#btn-subnet-map-save") == "Use for this upload"
    assert window_upload_is_none(await app_page.evaluate("() => window.__upload"))
    await app_page.locator("#subnet-map-rows .subnet-cidr").first.fill("192.168.1.0/24")
    await app_page.locator("#subnet-map-rows .subnet-name").first.fill("eth0")
    await app_page.click("#btn-subnet-map-save")
    assert "eth0 192.168.1.0/24" in await app_page.inner_text("#upload-subnet-summary")
    await app_page.evaluate("() => onUploadCaptureClick()")
    await app_page.wait_for_function("() => window.__upload !== null")
    sent = await app_page.evaluate("() => decodeURIComponent(window.__upload)")
    assert '"cidr":"192.168.1.0/24"' in sent and '"name":"eth0"' in sent
    # Done with: the next upload starts clean.
    assert not await app_page.is_checked("#upload-multi-iface")


def window_upload_is_none(value):
    return value is None


async def test_skipping_the_mapping_unticks_the_box(app_page):
    await _capture_panel(app_page)
    await app_page.click("#btn-upload-toggle")
    await app_page.check("#upload-multi-iface")
    await app_page.wait_for_selector("#subnet-map-dialog[open]")
    await app_page.click("#subnet-map-dialog [data-close-dialog]")
    # The dialog's close event fires after the click returns.
    await app_page.wait_for_function("() => !document.getElementById('upload-multi-iface').checked")


async def test_the_diagram_windows_can_be_resized(app_page):
    await _open_named(app_page)
    assert await app_page.evaluate("() => getComputedStyle(document.getElementById('topology-dialog')).resize") == "both"
    before = await app_page.evaluate("() => topologyState.width")
    await app_page.evaluate("() => { document.getElementById('topology-dialog').style.width = '700px'; }")
    await app_page.wait_for_function(f"() => topologyState.width < {before}")
