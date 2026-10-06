"""The two viewer filter surfaces that only exist in the browser.

Neither can be seen from an HTTP test. The autocomplete is a constant list in
app.js driven by keystrokes, and whether a panel can be scrolled to its end is
a question about CSS -- the API is green either way.

The viewer normally opens only for a completed capture, which needs a real
pcap and a real tshark. These tests unhide the viewer instead and drive the
filter box directly: the handlers are bound at page load regardless of whether
a capture is open, so what is under test here is the same code a real session
runs, without dragging a capture pipeline into a CSS and keyboard test.
"""

from __future__ import annotations

import pytest

from tests.browser.conftest import BROWSER_LOOP, needs_browser
from tests.test_packet_parser import needs_tshark

pytestmark = [needs_browser, BROWSER_LOOP]


async def _viewer(page):
    # No standing Viewer tab: it exists only while a capture is open in it.
    # These drive the panel directly, as the module docstring explains.
    await page.evaluate("() => activatePanel('viewer')")
    await page.wait_for_selector("#panel-viewer.active")
    # The viewer is empty until a capture is chosen; the filter box and its
    # handlers exist regardless.
    await page.evaluate("document.getElementById('packet-viewer').hidden = false")
    await page.wait_for_selector("#display-filter", state="visible")
    return page


# --- autocomplete ------------------------------------------------------------


async def test_typing_a_protocol_prefix_offers_completions(app_page):
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "tc")

    await app_page.wait_for_selector("#display-filter-ac .filter-ac-item")
    tokens = await app_page.eval_on_selector_all(
        "#display-filter-ac .filter-ac-token", "els => els.map(e => e.textContent)"
    )
    assert "tcp" in tokens


async def test_a_bare_protocol_is_offered_before_its_fields(app_page):
    """`tcp` is a complete filter on its own; `tcp.port` is not. The one that
    can be used as typed comes first."""
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "tc")

    await app_page.wait_for_selector("#display-filter-ac .filter-ac-item")
    tokens = await app_page.eval_on_selector_all(
        "#display-filter-ac .filter-ac-token", "els => els.map(e => e.textContent)"
    )
    assert tokens[0] == "tcp"


async def test_matching_is_not_limited_to_the_start_of_a_field_name(app_page):
    """Nobody remembers that the SYN flag is spelled tcp.flags.syn."""
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "syn")

    await app_page.wait_for_selector("#display-filter-ac .filter-ac-item")
    tokens = await app_page.eval_on_selector_all(
        "#display-filter-ac .filter-ac-token", "els => els.map(e => e.textContent)"
    )
    assert "tcp.flags.syn" in tokens


async def test_enter_takes_the_highlighted_completion(app_page):
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "kerb")
    await app_page.wait_for_selector("#display-filter-ac .filter-ac-item")
    await app_page.keyboard.press("Enter")

    assert await app_page.input_value("#display-filter") == "kerberos"
    assert await app_page.is_hidden("#display-filter-ac")


async def test_a_field_completion_leaves_room_for_the_comparison(app_page):
    """A field name is not a filter by itself, so the caret lands on a space
    ready for the operator rather than jammed against the name."""
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "ip.add")
    await app_page.wait_for_selector("#display-filter-ac .filter-ac-item")
    await app_page.keyboard.press("Tab")

    assert await app_page.input_value("#display-filter") == "ip.addr "


async def test_arrow_keys_move_the_highlight(app_page):
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "tcp.f")
    await app_page.wait_for_selector("#display-filter-ac .filter-ac-item")

    first = await app_page.eval_on_selector(
        "#display-filter-ac .filter-ac-item[aria-selected='true'] .filter-ac-token",
        "e => e.textContent",
    )
    await app_page.keyboard.press("ArrowDown")
    second = await app_page.eval_on_selector(
        "#display-filter-ac .filter-ac-item[aria-selected='true'] .filter-ac-token",
        "e => e.textContent",
    )
    assert first != second


async def test_escape_closes_the_list_without_changing_the_box(app_page):
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "dn")
    await app_page.wait_for_selector("#display-filter-ac .filter-ac-item")
    await app_page.keyboard.press("Escape")

    assert await app_page.is_hidden("#display-filter-ac")
    assert await app_page.input_value("#display-filter") == "dn"


async def test_completing_a_token_mid_expression_leaves_the_rest_alone(app_page):
    """The match is on the token under the caret, not the whole box."""
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "ip.addr == 10.0.0.1 && kerb")
    await app_page.wait_for_selector("#display-filter-ac .filter-ac-item")
    await app_page.keyboard.press("Enter")

    assert await app_page.input_value("#display-filter") == "ip.addr == 10.0.0.1 && kerberos"


async def test_a_fully_typed_token_is_not_offered_back(app_page):
    """Accepting it would change nothing, and it costs a row that a real
    completion could use."""
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "kerberos")
    tokens = await app_page.eval_on_selector_all(
        "#display-filter-ac .filter-ac-token", "els => els.map(e => e.textContent)"
    )
    assert "kerberos" not in tokens
    assert "kerberos.CNameString" in tokens


async def test_the_list_closes_when_nothing_is_left_to_offer(app_page):
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "zzznotafield")
    assert await app_page.is_hidden("#display-filter-ac")


# --- the capture filter library can be scrolled ------------------------------


async def test_the_filter_library_sits_in_a_scroll_container(app_page):
    """.panel is overflow:hidden. Before this the library expanded past the
    bottom of the capture panel and was clipped with no scrollbar anywhere --
    the end of an eighty-entry list was simply unreachable."""
    await app_page.click(".tab[data-tab='capture']")
    await app_page.wait_for_selector("#panel-capture.active")
    await app_page.click("#filter-library-details > summary")
    await app_page.wait_for_selector("#filter-library .filter-group")

    box = await app_page.evaluate("""() => {
        const el = document.querySelector(".filter-library-scroll");
        if (!el) return null;
        const style = getComputedStyle(el);
        return {
            overflowY: style.overflowY,
            scrollable: el.scrollHeight > el.clientHeight,
        };
    }""")
    assert box is not None, "the library has no scroll container"
    assert box["overflowY"] == "auto"
    assert box["scrollable"], "the library fits its box, so nothing is being clipped either"


async def test_the_capture_panel_itself_scrolls(app_page):
    """The library is not the only thing below the fold once it is open: the
    explainers and the capture list are under it."""
    await app_page.click(".tab[data-tab='capture']")
    await app_page.wait_for_selector("#panel-capture.active")
    overflow = await app_page.eval_on_selector(
        "#panel-capture", "el => getComputedStyle(el).overflowY"
    )
    assert overflow == "auto"


async def test_the_library_actually_scrolls_when_asked(app_page):
    await app_page.click(".tab[data-tab='capture']")
    await app_page.wait_for_selector("#panel-capture.active")
    await app_page.click("#filter-library-details > summary")
    await app_page.wait_for_selector("#filter-library .filter-group")

    moved = await app_page.evaluate("""() => {
        const el = document.querySelector(".filter-library-scroll");
        el.scrollTop = 200;
        return el.scrollTop;
    }""")
    assert moved > 0


# --- saved view tabs ---------------------------------------------------------
#
# The API side is covered in tests/test_capture_views.py. What that cannot show
# is the strip itself: whether it stays out of the way until there is something
# to show, which tab reads as selected, and whether the per-tab actions are
# reachable. Driving renderViewTabs directly rather than opening a real capture
# keeps a rendering test out of the capture pipeline -- app.js is a classic
# script, so its top-level bindings are reachable from evaluate().


async def _render_tabs(page, views, active=""):
    # No standing Viewer tab: it exists only while a capture is open in it.
    # These drive the panel directly, as the module docstring explains.
    await page.evaluate("() => activatePanel('viewer')")
    await page.wait_for_selector("#panel-viewer.active")
    await page.evaluate(
        """([views, active]) => {
            document.getElementById("packet-viewer").hidden = false;
            savedViews = views;
            activeViewId = active;
            renderViewTabs();
        }""",
        [views, active],
    )


async def test_the_tab_strip_is_hidden_until_a_view_is_saved(app_page):
    """An operator who never saves one should not pay a line of chrome."""
    await _render_tabs(app_page, [])
    assert await app_page.is_hidden("#view-tabs")


async def test_saved_views_appear_as_tabs_after_all_packets(app_page):
    await _render_tabs(app_page, [
        {"id": "v1", "name": "auth traffic", "display_filter": "kerberos"},
        {"id": "v2", "name": "retransmissions", "display_filter": "tcp.analysis.retransmission"},
    ])
    names = await app_page.eval_on_selector_all(
        "#view-tabs .view-tab-name", "els => els.map(e => e.textContent)"
    )
    assert names == ["All packets", "auth traffic", "retransmissions"]


async def test_all_packets_is_selected_by_default_and_cannot_be_removed(app_page):
    """It is not a saved row -- it is what the viewer shows with an empty
    filter, so there is nothing to rename or delete."""
    await _render_tabs(app_page, [{"id": "v1", "name": "dns", "display_filter": "dns"}])
    selected = await app_page.eval_on_selector(
        "#view-tabs .view-tab[aria-selected='true'] .view-tab-name", "e => e.textContent"
    )
    assert selected == "All packets"

    actions = await app_page.eval_on_selector(
        "#view-tabs .view-tab", "el => el.querySelectorAll('[data-action]').length"
    )
    assert actions == 0  # only the tab's own select-view, no per-view buttons


async def test_the_selected_view_offers_download_edit_and_delete(app_page):
    await _render_tabs(
        app_page,
        [{"id": "v1", "name": "dns", "display_filter": "dns"}],
        active="v1",
    )
    actions = await app_page.eval_on_selector_all(
        "#view-tabs .view-tab[aria-selected='true'] .view-tab-action",
        "els => els.map(e => e.dataset.action)",
    )
    assert actions == ["download-view", "edit-view", "delete-view"]


async def test_clicking_a_tab_puts_its_filter_in_the_box(app_page):
    await _render_tabs(app_page, [{"id": "v1", "name": "dns", "display_filter": "dns"}])
    await app_page.click("#view-tabs .view-tab[data-id='v1']")
    assert await app_page.input_value("#display-filter") == "dns"


async def test_typing_over_a_views_filter_deselects_that_view(app_page):
    """The tab claimed you were looking at "dns" while the box said something
    else. Editing by hand means you have left the view."""
    await _render_tabs(
        app_page,
        [{"id": "v1", "name": "dns", "display_filter": "dns"}],
        active="v1",
    )
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "udp")

    selected = await app_page.eval_on_selector(
        "#view-tabs .view-tab[aria-selected='true'] .view-tab-name", "e => e.textContent"
    )
    assert selected == "All packets"


async def test_a_view_name_cannot_inject_markup_into_the_strip(app_page):
    await _render_tabs(app_page, [
        {"id": "v1", "name": "<img src=x onerror=alert(1)>", "display_filter": "tcp"},
    ])
    name = await app_page.eval_on_selector(
        "#view-tabs .view-tab[data-id='v1'] .view-tab-name", "e => e.textContent"
    )
    assert name == "<img src=x onerror=alert(1)>"
    assert await app_page.eval_on_selector_all("#view-tabs img", "els => els.length") == 0


async def test_the_display_filter_sits_below_the_capture_label(app_page):
    """They used to share a row.

    That cost the filter half the width on a narrow window, and put the name
    of the capture and the thing you are doing to it on one line as though
    they were the same kind of thing. The label takes a row of its own now and
    the filter has the row below it, so this compares their vertical positions
    rather than their order in the DOM -- flex-wrap decides the layout, and the
    DOM order did not change.
    """
    await _viewer(app_page)
    # The label is filled when a capture is opened; this file drives the viewer
    # without one, so it is given something to measure.
    await app_page.evaluate(
        "document.getElementById('viewer-capture-label').textContent = "
        "'capture-2026-09-13.pcap \u00b7 1,204 packets'"
    )

    box = await app_page.evaluate(
        """() => {
            const label = document.getElementById("viewer-capture-label");
            const filter = document.getElementById("display-filter");
            const l = label.getBoundingClientRect();
            const f = filter.getBoundingClientRect();
            return {labelBottom: l.bottom, filterTop: f.top, labelWidth: l.width,
                    toolbarWidth: label.parentElement.getBoundingClientRect().width};
        }"""
    )

    assert box["filterTop"] >= box["labelBottom"] - 1, \
        "the filter must start at or below the bottom of the label, not beside it"
    assert box["labelWidth"] > box["toolbarWidth"] * 0.8, \
        "the label should own its row rather than sharing it"


# --- saved display filters ---------------------------------------------------


async def test_the_viewer_save_button_appears_only_with_a_filter_and_left_of_the_box(app_page):
    await _viewer(app_page)
    await app_page.fill("#display-filter", "")
    assert await app_page.is_hidden("#btn-save-display-filter")
    await app_page.fill("#display-filter", "dns")
    await app_page.wait_for_selector("#btn-save-display-filter", state="visible")
    button = await app_page.locator("#btn-save-display-filter").bounding_box()
    field = await app_page.locator("#display-filter").bounding_box()
    assert button["x"] + button["width"] <= field["x"]


async def test_saving_a_display_filter_lists_it_under_filter_help(app_page, api_client):
    await _viewer(app_page)
    await app_page.fill("#display-filter", "tcp.analysis.retransmission")

    async def name_it(dialog):
        await dialog.accept("retransmits")

    app_page.on("dialog", name_it)
    try:
        await app_page.click("#btn-save-display-filter")
        await app_page.wait_for_selector("#display-own-filters .filter-chip:has-text('retransmits')")
        assert await app_page.is_visible("#drawer-filter-help")
        saved = api_client.get("/api/display-filters").json()
        assert [(f["label"], f["expression"]) for f in saved] == [("retransmits", "tcp.analysis.retransmission")]
    finally:
        app_page.remove_listener("dialog", name_it)
        for f in api_client.get("/api/display-filters").json():
            api_client.delete(f"/api/display-filters/{f['id']}")


async def test_choosing_a_saved_display_filter_fills_the_box(app_page, api_client):
    created = api_client.post("/api/display-filters",
                              json={"label": "just dns", "expression": "dns"}).json()
    try:
        await _viewer(app_page)
        await app_page.evaluate("() => loadDisplayFilters()")
        await app_page.evaluate("() => { const o = openDrawers(); if (!o.has('filter-help')) toggleDrawer('filter-help'); }")
        await app_page.fill("#display-filter", "")
        await app_page.click("#display-own-filters .filter-chip:has-text('just dns')")
        assert await app_page.input_value("#display-filter") == "dns"
    finally:
        api_client.delete(f"/api/display-filters/{created['id']}")


async def test_a_saved_display_filter_label_cannot_inject_markup(app_page, api_client):
    created = api_client.post("/api/display-filters",
                              json={"label": "<img src=x onerror=alert(1)>", "expression": "arp"}).json()
    try:
        await _viewer(app_page)
        await app_page.evaluate("() => loadDisplayFilters()")
        assert await app_page.locator("#display-own-filters img").count() == 0
    finally:
        api_client.delete(f"/api/display-filters/{created['id']}")


async def test_go_to_packet_selects_the_row_or_says_why_not(app_page):
    await _viewer(app_page)
    await app_page.evaluate("""() => {
        viewingCaptureId = 'cap-go';
        currentPackets = [{ number: 1 }, { number: 2 }, { number: 3 }];
        document.getElementById('packet-tbody').innerHTML =
            [1, 2, 3].map((n) => `<tr data-frame="${n}"><td>${n}</td></tr>`).join('');
        window.__opened = [];
        selectPacket = async (n) => { window.__opened.push(n); };
    }""")
    await app_page.fill("#goto-packet", "2")
    await app_page.press("#goto-packet", "Enter")
    assert await app_page.evaluate("() => window.__opened") == [2]
    await app_page.fill("#goto-packet", "900")
    await app_page.press("#goto-packet", "Enter")
    assert await app_page.evaluate("() => window.__opened") == [2, 900]
    assert "past the 3 rows" in await app_page.inner_text("#goto-packet-msg")


# --- the rest of tshark's names ----------------------------------------------
#
# The built-in list is a hundred and thirty names; the registry is a quarter of
# a million, and it is asked through the server. These two need a real tshark
# behind the app the browser is talking to.


@needs_tshark
async def test_a_name_the_builtin_list_lacks_comes_from_tsharks_registry(app_page):
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "tcp.analysis.byt")

    await app_page.wait_for_selector("#display-filter-ac .filter-ac-item")
    tokens = await app_page.eval_on_selector_all(
        "#display-filter-ac .filter-ac-token", "els => els.map(e => e.textContent)"
    )
    assert tokens == ["tcp.analysis.bytes_in_flight"]


@needs_tshark
async def test_registry_names_are_added_under_the_builtin_ones_not_shuffled_in(app_page):
    """A list that reorders under the arrow keys picks the wrong row."""
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "kerb")
    # A function, not a string: the page's CSP has no unsafe-eval.
    await app_page.wait_for_function(
        "() => document.querySelectorAll('#display-filter-ac .filter-ac-item').length > 2"
    )
    tokens = await app_page.eval_on_selector_all(
        "#display-filter-ac .filter-ac-token", "els => els.map(e => e.textContent)"
    )
    assert tokens[0] == "kerberos"
    assert len(tokens) == len(set(tokens)), "a name was offered twice"


# --- valid or not, before applying -------------------------------------------


@needs_tshark
async def test_the_box_says_whether_what_is_typed_is_a_filter(app_page):
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "tcp.port ==")
    await app_page.keyboard.press("Escape")
    await app_page.wait_for_selector("#display-filter-state[data-state='bad']")
    assert "invalid" in await app_page.text_content("#display-filter-state")
    assert await app_page.get_attribute("#display-filter", "aria-invalid") == "true"
    # tshark's own words, as the mark's tooltip.
    assert "end of filter" in (await app_page.get_attribute("#display-filter-state", "title"))

    await app_page.type("#display-filter", " 443")
    await app_page.wait_for_selector("#display-filter-state[data-state='ok']")
    assert await app_page.get_attribute("#display-filter", "aria-invalid") is None


async def test_an_emptied_box_has_no_verdict(app_page):
    await _viewer(app_page)
    await app_page.click("#display-filter")
    await app_page.type("#display-filter", "t")
    await app_page.evaluate("setFilterState('bad', 'x')")
    assert await app_page.is_visible("#display-filter-state")
    await app_page.keyboard.press("Backspace")
    assert await app_page.is_hidden("#display-filter-state")


# --- building a filter: quoting, combining, the selected packet's fields ------


async def test_the_menu_combines_the_six_ways_wireshark_does(app_page):
    await _viewer(app_page)
    await app_page.fill("#display-filter", "tcp")
    combined = await app_page.evaluate(
        "['selected','not','and','or','andnot','ornot'].map(m => combineFilter('ip.addr == 10.0.0.1', m))"
    )
    assert combined == [
        "ip.addr == 10.0.0.1",
        "!(ip.addr == 10.0.0.1)",
        "(tcp) && (ip.addr == 10.0.0.1)",
        "(tcp) || (ip.addr == 10.0.0.1)",
        "(tcp) && !(ip.addr == 10.0.0.1)",
        "(tcp) || !(ip.addr == 10.0.0.1)",
    ]
    await app_page.fill("#display-filter", "")
    alone = await app_page.evaluate("['and','andnot','ornot'].map(m => combineFilter('dns', m))")
    assert alone == ["dns", "!(dns)", "!(dns)"]


async def test_a_text_value_with_a_backslash_or_a_quote_is_escaped_not_dropped(app_page):
    """These used to fall back to a bare presence test, because the server
    refused a backslash anywhere in a filter."""
    await _viewer(app_page)
    built = await app_page.evaluate(
        r"""[
            buildFieldFilter('smb2.filename', 'share\\dir\\file.txt'),
            buildFieldFilter('http.user_agent', 'say "hi"; $HOME'),
            buildFieldFilter('ip.src', '10.0.0.1'),
            buildFieldFilter('http.file_data', 'two\nlines'),
        ]"""
    )
    assert built == [
        r'smb2.filename == "share\\dir\\file.txt"',
        r'http.user_agent == "say \"hi\"; $HOME"',
        "ip.src == 10.0.0.1",
        "http.file_data",
    ]


async def test_a_field_reference_is_filled_in_from_the_selected_packet(app_page):
    await _viewer(app_page)
    resolved = await app_page.evaluate(
        """() => {
            currentDetail = { layers: [
                { name: 'ip', fields: [{ name: 'ip.src', value: '10.0.0.7' }] },
                { name: 'http', fields: [{ name: 'http.request', children: [
                    { name: 'http.host', value: 'example.com' }] }] },
            ] };
            return [
                resolveFieldReferences('ip.addr == ${ip.src} && http.host == ${ http.host }'),
                resolveFieldReferences('http.request.uri contains "${ip.src}"'),
                resolveFieldReferences('tcp.port == ${tcp.srcport}'),
            ];
        }"""
    )
    assert resolved[0] == {"text": 'ip.addr == 10.0.0.7 && http.host == "example.com"'}
    assert resolved[1] == {"text": 'http.request.uri contains "${ip.src}"'}, "a quoted string is text to search for"
    assert "no tcp.srcport" in resolved[2]["error"]


async def test_a_field_reference_with_no_packet_selected_says_to_select_one(app_page):
    await _viewer(app_page)
    resolved = await app_page.evaluate(
        "() => { currentDetail = null; return resolveFieldReferences('ip.addr == ${ip.src}'); }"
    )
    assert "Click a packet" in resolved["error"]


# --- how much of the answer is on screen --------------------------------------


async def test_the_count_says_what_matched_and_how_much_of_it_is_shown(app_page):
    await _viewer(app_page)
    texts = await app_page.evaluate(
        """() => {
            const rows = (n) => Array.from({ length: n }, (_, i) => ({ number: i + 1 }));
            const say = (shown, page) => { currentPackets = rows(shown); packetPage = { captureId: 'c', loading: false, ...page }; return [packetCountText(), packetMoreRowHtml(8) !== '']; };
            return [
                say(700, { filter: '', matched: 700, total: 700 }),
                say(40, { filter: 'dns', matched: 40, total: 700 }),
                say(1, { filter: 'frame.number == 1', matched: 1, total: 700 }),
                say(1000, { filter: 'tcp', matched: 4213, total: 12000 }),
                say(1000, { filter: '', matched: 12000, total: 12000 }),
                say(3, { filter: 'udp', matched: 3, total: 0 }),
            ];
        }"""
    )
    assert texts == [
        ["700 packets", False],
        ["40 packets of 700 match", False],
        ["1 packet of 700 matches", False],
        ["4,213 packets of 12,000 match · first 1,000 shown", True],
        ["12,000 packets · first 1,000 shown", True],
        ["3 packets match", False],
    ]
