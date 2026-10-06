# Design note: what Wireshark's filter still does that the Viewer does not

*Status: a list of things not built, written 2026-10-06 after the display
filter work recorded under "Unreleased" in the changelog. Nothing here is
scheduled.*

The Viewer hands a display filter to `tshark -Y` as written, so the language
is Wireshark's. That work closed the gaps around the box: regular expressions,
a count of what matched and paging through it, completion from tshark's
registry, a verdict while typing, `${field}` references, and the full
right-click menu. What follows is what Wireshark does with a display filter
that the Viewer still does not, roughly in the order it is likely to be missed.

## Fields that need two passes

**What is missing.** Fields that point forward in the capture never match:
`dns.response_in`, `http.response_in`, `tcp.reassembled_in` and the rest of
the `*_in` family. Wireshark fills them in because it reads the file twice.

**Why.** tshark does the same with `-2`, and `-2` needs a file it can seek in.
A capture reaches tshark here as a pipe on stdin (`backend/pcapsource.py`), so
that the decrypted bytes never exist as a file. Measured on tshark 4.4.18:
`-2` on a pipe fails with "TShark can't read pipe or FIFO files in two-pass
mode"; the same capture in a `memfd` matched.

**What it would take.** Write the decrypted capture to a `memfd` and pass
tshark `/proc/self/fd/N`. It is anonymous memory, never on disk, but it holds
the whole decrypted capture in RAM for the length of the run and is readable
through `/proc` by the same user. That is a change to the rule the vault was
built on, so it is a decision before it is a patch. The user left it out on
2026-10-06.

## Find Packet

Wireshark's Ctrl+F: jump to the next packet matching a display filter, a hex
string, a text string or a regular expression, without narrowing the list.
The Viewer has **Go to #** (by number) and nothing for "the next one like
this". A filter-based find is one more `-T fields -e frame.number` pass with
the filter, returning frame numbers to step through; the list would need to
load the page a match is on.

## Colouring rules that are display filters

Wireshark colours rows by an ordered list of display filters, which the user
can edit. The Viewer's row colours are a fixed list of tests written in
JavaScript against the Protocol and Info columns (`PACKET_RULES` in
`frontend/js/app.js`). Editable rules would mean asking tshark which rule each
packet matches (`-T fields -e frame.coloring_rule.name` with a `colorfilters`
file in a profile directory), and a per-account store for the rules.
"Colourise conversation" is the same mechanism with a temporary rule.

## Decode As

Telling Wireshark that port 8443 is TLS, or that a UDP port is RTP. Until
then `tls` and `http` filters do not match traffic on a port tshark does not
recognise. tshark takes it as `-d tcp.port==8443,tls`; `-G decodes` lists what
is valid. It needs a per-capture setting, a strictly validated argument (it is
argv, and the selector and protocol names both come from the user), and it has
to reach every tshark call for that capture, not only the list.

## TLS decryption

With a key log file Wireshark shows HTTP inside TLS, and `http` filters match
it. tshark takes `-o tls.keylog_file:<path>`. The key log is a secret that
decrypts the capture's traffic: it would have to be uploaded, sealed by the
vault like a capture, and handed to tshark without becoming a plaintext file,
which is the same question as two-pass.

## Display filter macros

`$name(args)` expands a saved, parameterised filter. tshark reads macros from
a `dfilter_macros` file in its profile directory, which the image does not
have. **Save filter** covers the unparameterised case. Parameterised macros
would be a per-account store plus either writing that file per request or
expanding them in the app before the filter is sent.

## Smaller things

- **Values in completion.** The box completes field names, not values.
  `tshark -G values` lists the named values of every field (`dns.qry.type` is
  1 for A, 28 for AAAA); 1.6 million lines, so it would be looked up by field.
- **A filter expression builder.** Wireshark's dialog for browsing fields and
  picking an operator. Completion from the registry covers most of it.
- **Filter history.** The last filters applied, on a drop-down from the box.
- **Marked and ignored packets, and time references.** `frame.marked`,
  `frame.ignored` and `frame.ref_time` are state Wireshark keeps per session;
  the Viewer has no per-packet state.
- **Conversation filter at the Ethernet layer.** Offered for IP pairs and for
  TCP and UDP streams. A MAC pair needs the MAC columns on, and a cooked
  capture (`any`) records no destination MAC.
- **The filter in Expert Information and I/O graphs.** Neither dialog exists
  here. `_ws.expert` already works as a filter.
