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


async def test_topology_node_click_applies_pair_filter_and_closes(app_page):
    await _stub_api(app_page, "/conversations", CONVERSATIONS_PAYLOAD)
    await _open_viewer(app_page)

    await app_page.click("#btn-topology")
    await app_page.wait_for_selector("#topology-dialog[open]")
    await app_page.evaluate(
        """() => {
            const g = [...document.querySelectorAll('.diagram-node')]
                .find((n) => n.querySelector('text').textContent === '10.0.0.1');
            g.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        }"""
    )

    assert await app_page.input_value("#display-filter") == "ip.addr == 10.0.0.1"
    assert await app_page.locator("#topology-dialog[open]").count() == 0


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
    await _stub_api(app_page, "/packets?", payload)
    await _open_viewer(app_page)

    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")

    assert await app_page.locator("#sequence-svg .seq-lane-line").count() == 3
    assert await app_page.locator("#sequence-svg .seq-arrow").count() == 3
    legend = await app_page.inner_text("#sequence-legend")
    assert "TCP" in legend and "UDP" in legend and "DNS" in legend


async def test_sequence_arrow_click_opens_the_packet_and_closes(app_page):
    payload = {"packets": [_packet(7, "10.0.0.1", "10.0.0.2")], "total": 1}
    await _stub_api(app_page, "/packets?", payload)
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


async def test_sequence_cap_warning_when_packets_exceed_the_limit(app_page):
    await _stub_api(app_page, "/packets?", {"packets": [], "total": 5001})
    await _open_viewer(app_page)

    await app_page.click("#btn-sequence")
    await app_page.wait_for_selector("#sequence-dialog[open]")

    assert await app_page.is_visible("#sequence-cap-warning")
    assert "5,001" in await app_page.inner_text("#sequence-cap-warning") \
        or "5001" in await app_page.inner_text("#sequence-cap-warning")
    assert await app_page.is_hidden("#sequence-body")
