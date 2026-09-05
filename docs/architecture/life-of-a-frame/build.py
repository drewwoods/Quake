#!/usr/bin/env python3
"""Build quake-life-of-a-frame.html from the seven markdown sections.

Stdlib only. Implements the markdown subset the sources actually use:
headings, paragraphs, fenced code, inline code, bold/italic, links,
bullet/numbered lists, tables, blockquotes, horizontal rules.

Plus Quake-specific transforms:
  * WinQuake/file.c:NNN[-MMM]  ->  link to upstream id-Software/Quake
  * ``` fences               ->  <figure class="code"> with a ref header bar
  * "## Call graph" fence     ->  nested collapsible <details> tree
  * "## Key data structures"  ->  table
  * "## Further reading"      ->  link list
"""

import html
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sections")
OUT = os.path.join(HERE, "quake-life-of-a-frame.html")

GH = "https://github.com/id-Software/Quake/blob/master/WinQuake/"

FILES = [
    ("01-frame-overview.md", "Frame"),
    ("02-server-physics-progs.md", "Server"),
    ("03-collision.md", "Collision"),
    ("04-bsp-pvs.md", "World"),
    ("05-rendering.md", "Render"),
    ("06-input-client-net.md", "Client"),
    ("07-sound-misc.md", "Sound"),
]

# ---------------------------------------------------------------- refs

# WinQuake/foo.c:12-34  |  WinQuake/foo.h:12  |  WinQuake/foo.c
REF_QUALIFIED = re.compile(r"WinQuake/([A-Za-z0-9_]+\.[ch])(?::(\d+)(?:-(\d+))?)?")
# bare foo.c:12 — only used inside call-graph trees, where it is unambiguous
REF_BARE = re.compile(r"\b([A-Za-z0-9_]+\.[ch]):(\d+)(?:-(\d+))?")


def ref_url(fname, start, end):
    u = GH + fname
    if start:
        u += "#L" + start
        if end:
            u += "-L" + end
    return u


def link_refs(text, bare=False):
    """Linkify WinQuake refs in already-HTML-escaped text."""

    def sub(m):
        fname, start, end = m.group(1), m.group(2), m.group(3)
        label = m.group(0)
        return ('<a class="ref" target="_blank" rel="noopener" href="%s">%s</a>'
                % (ref_url(fname, start, end), label))

    return (REF_BARE if bare else REF_QUALIFIED).sub(sub, text)


def first_ref(text):
    m = REF_QUALIFIED.search(text)
    return m.group(0) if m else None


def last_ref(text):
    ms = list(REF_QUALIFIED.finditer(text))
    return ms[-1].group(0) if ms else None


def ref_link_html(ref):
    m = REF_QUALIFIED.fullmatch(ref)
    if not m:
        return html.escape(ref)
    return ('<a class="ref" target="_blank" rel="noopener" href="%s">%s</a>'
            % (ref_url(m.group(1), m.group(2), m.group(3)), html.escape(ref)))


# ---------------------------------------------------------------- inline

CODE_SPAN = re.compile(r"`([^`]+)`")
MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BARE_URL = re.compile(r"(?<![\"=>])\bhttps?://[^\s<>()]+[^\s<>().,;:]")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
ITAL = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")


def inline(text):
    """Markdown inline -> HTML. Input is raw (unescaped) markdown."""
    spans = []

    def stash(m):
        spans.append(m.group(1))
        return "\x00%d\x00" % (len(spans) - 1)

    text = CODE_SPAN.sub(stash, text)

    links = []

    def stash_link(m):
        label, url = m.group(1), m.group(2)
        external = re.match(r"https?://", url)
        if not external and not url.startswith("#"):
            url = os.path.relpath(os.path.join(SRC, url), HERE)
        links.append('<a%s href="%s">%s</a>'
                     % (' target="_blank" rel="noopener"' if external else '',
                        html.escape(url, quote=True), inline(label)))
        return "\x01%d\x01" % (len(links) - 1)

    text = MD_LINK.sub(stash_link, text)

    text = html.escape(text)

    def stash_bare(m):
        url = m.group(0)
        links.append('<a target="_blank" rel="noopener" href="%s">%s</a>'
                     % (url, url))
        return "\x01%d\x01" % (len(links) - 1)

    text = BARE_URL.sub(stash_bare, text)

    text = BOLD.sub(r"<strong>\1</strong>", text)
    text = ITAL.sub(r"<em>\1</em>", text)
    text = link_refs(text)

    def unstash(m):
        body = link_refs(html.escape(spans[int(m.group(1))]))
        return "<code>%s</code>" % body

    text = re.sub(r"\x00(\d+)\x00", unstash, text)
    text = re.sub(r"\x01(\d+)\x01", lambda m: links[int(m.group(1))], text)
    return text


# ---------------------------------------------------------------- slugs

_slugs = set()


def slugify(text):
    s = re.sub(r"`|\*", "", text).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = s or "sec"
    base, n = s, 2
    while s in _slugs:
        s = "%s-%d" % (base, n)
        n += 1
    _slugs.add(s)
    return s


# ---------------------------------------------------------------- blocks

_code_seq = [0]


def render_code(code, lang, ref, folded=False, idx=0):
    label = ref_link_html(ref) if ref else html.escape(lang or "listing")
    tag = "C" if lang == "c" else "TEXT"
    body = ('<div class="code-bar"><span class="code-fold-toggle" aria-hidden="true"></span>'
            '<span class="code-lang">%s</span>'
            '<span class="code-ref">%s</span></div>'
            '<div class="code-scroll"><pre><code class="lang-%s">%s</code></pre></div>'
            % (tag, label, lang or "text", html.escape(code)))
    if folded:
        summary = ref_link_html(ref) if ref else "further excerpt"
        return ('<details class="code fold"><summary><span class="fold-label">'
                'Excerpt</span> %s</summary>%s</details>' % (summary, body))
    _code_seq[0] += 1
    return ('<figure class="code" data-fold-id="c%d">%s</figure>'
             % (_code_seq[0], body))


def render_calltree(code):
    """Indented text tree -> nested <details>.

    Some sections draw the tree with box-drawing glyphs instead of plain
    indentation; those already carry their own structure, so render them
    verbatim in a mono block rather than re-deriving nesting from columns.
    """
    if re.search(r"[│├└─]", code):
        return ('<div class="calltree ascii"><pre>%s</pre></div>'
                % link_refs(html.escape(code), bare=True))

    rows = []
    for raw in code.split("\n"):
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        rest = raw.strip()
        parts = re.split(r"\s{2,}", rest, maxsplit=1)
        name = parts[0]
        ref = parts[1] if len(parts) > 1 else ""
        rows.append((indent // 2, name, ref))

    def fmt(name, ref):
        n = link_refs(html.escape(name), bare=True)
        n = '<span class="ct-name">%s</span>' % n
        if ref:
            r = link_refs(html.escape(ref), bare=True)
            n += '<span class="ct-ref">%s</span>' % r
        return n

    out = []

    def emit(i, depth):
        while i < len(rows):
            lvl, name, ref = rows[i]
            if lvl < depth:
                return i
            kids = i + 1 < len(rows) and rows[i + 1][0] > lvl
            if kids:
                out.append('<details class="ct" open><summary>%s</summary><div class="ct-kids">'
                           % fmt(name, ref))
                i = emit(i + 1, lvl + 1)
                out.append("</div></details>")
            else:
                out.append('<div class="ct-leaf">%s</div>' % fmt(name, ref))
                i += 1
        return i

    emit(0, 0)
    return '<div class="calltree">%s</div>' % "".join(out)


KDS_ITEM = re.compile(r"^\s*[-*]\s+(.*)$")


def render_kds(items):
    rows = []
    for it in items:
        parts = [p.strip() for p in re.split(r"\s+—\s+", it)]
        if len(parts) >= 3:
            sym, loc, purpose = parts[0], parts[1], " — ".join(parts[2:])
        elif len(parts) == 2:
            sym, loc, purpose = parts[0], "", parts[1]
        else:
            sym, loc, purpose = parts[0], "", ""
        rows.append("<tr><th scope=\"row\">%s</th><td class=\"kds-loc\">%s</td><td>%s</td></tr>"
                    % (inline(sym), inline(loc), inline(purpose)))
    return ('<div class="table-scroll"><table class="kds">'
            '<thead><tr><th scope="col">Symbol</th><th scope="col">Declared</th>'
            '<th scope="col">Purpose</th></tr></thead><tbody>%s</tbody></table></div>'
            % "".join(rows))


def render_reading(items):
    lis = []
    for it in items:
        lis.append("<li>%s</li>" % inline(it))
    return '<ul class="reading">%s</ul>' % "".join(lis)


def render_table(lines):
    cells = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines]
    head = cells[0]
    body = cells[2:]
    th = "".join("<th scope=\"col\">%s</th>" % inline(c) for c in head)
    trs = []
    for row in body:
        trs.append("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in row))
    return ('<div class="table-scroll"><table class="grid"><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table></div>' % (th, "".join(trs)))


# ---------------------------------------------------------------- section

def convert(md, sec_index, sec_id, kicker):
    lines = md.split("\n")
    # join lazy continuation lines into the preceding line
    joined = []
    in_fence = False
    for ln in lines:
        if ln.startswith("```"):
            in_fence = not in_fence
            joined.append(ln)
            continue
        if (not in_fence and joined and ln.startswith(("  ", "\t"))
                and ln.strip() and not re.match(r"^\s*[-*]\s|^\s*\d+\.\s", ln)
                and joined[-1].strip()):
            joined[-1] = joined[-1].rstrip() + " " + ln.strip()
            continue
        joined.append(ln)
    lines = joined

    out = []
    nav = []
    title = None
    i = 0
    n = len(lines)
    mode = None            # None | 'callgraph' | 'kds' | 'reading'
    excerpt_count = 0      # code excerpts within the current subtopic
    open_sub = False       # a <section class="sub"> is open

    def close_sub():
        nonlocal open_sub
        if open_sub:
            out.append("</section>")
            open_sub = False

    while i < n:
        ln = lines[i]

        # --- authored, accessible diagrams ------------------------------
        diagram = re.fullmatch(r"::: diagram ([a-z0-9-]+)", ln)
        if diagram:
            with open(os.path.join(HERE, "diagrams", diagram.group(1) + ".html"),
                      encoding="utf-8") as f:
                out.append(link_refs(f.read()))
            i += 1
            continue

        # --- fenced code ------------------------------------------------
        if ln.startswith("```"):
            lang = ln[3:].strip()
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(buf).rstrip("\n")

            if mode == "callgraph":
                out.append(render_calltree(code))
                continue

            # ref for the header bar
            ref = None
            body = code.split("\n")
            if body and re.match(r"^\s*(//|/\*)\s*WinQuake/", body[0]):
                ref = first_ref(body[0])
                code = "\n".join(body[1:]).lstrip("\n")
            if not ref:
                for back in range(len(out) - 1, max(-1, len(out) - 4), -1):
                    r = last_ref(out[back]) if isinstance(out[back], str) else None
                    if r:
                        ref = r
                        break
            if not ref:
                for fwd in range(i, min(n, i + 3)):
                    if lines[fwd].strip():
                        ref = first_ref(lines[fwd])
                        break
            excerpt_count += 1
            folded = excerpt_count > 2 and len(code.split("\n")) > 6
            out.append(render_code(code, lang or "text", ref, folded, excerpt_count))
            continue

        # --- headings ---------------------------------------------------
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            level, text = len(m.group(1)), m.group(2).strip()
            plain = re.sub(r"`|\*\*", "", text)
            if level == 1:
                title = plain
                out.append('<h2 class="sec-title" id="%s" data-h="%s">'
                           '<span class="kicker">%02d · %s</span>%s</h2>'
                           % (sec_id, html.escape(plain, quote=True),
                              sec_index, html.escape(kicker), inline(text)))
                i += 1
                continue
            close_sub()
            slug = slugify(plain)
            mode = None
            excerpt_count = 0
            low = plain.lower()
            if low == "call graph":
                mode = "callgraph"
            elif low == "key data structures":
                mode = "kds"
            elif low == "further reading":
                mode = "reading"
            cls = "sub" + (" sub-appendix" if mode else "")
            out.append('<section class="%s">' % cls)
            open_sub = True
            tag = "h3" if level == 2 else "h4"
            out.append('<%s id="%s" data-h="%s" class="h-%d">'
                       '<a class="anchor" href="#%s" aria-label="Link to this heading">#</a>%s</%s>'
                       % (tag, slug, html.escape(plain, quote=True), level, slug,
                          inline(text), tag))
            nav.append({"id": slug, "text": plain, "minor": bool(mode), "sub": level == 3})
            i += 1
            continue

        # --- horizontal rule --------------------------------------------
        if re.match(r"^-{3,}\s*$", ln):
            out.append('<hr>')
            i += 1
            continue

        # --- table ------------------------------------------------------
        if ln.startswith("|") and i + 1 < n and re.match(r"^\|[\s\-:|]+\|\s*$", lines[i + 1]):
            tbl = []
            while i < n and lines[i].startswith("|"):
                tbl.append(lines[i])
                i += 1
            out.append(render_table(tbl))
            continue

        # --- blockquote --------------------------------------------------
        if ln.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            quote = " ".join(buf)
            cls = ' class="first-pass"' if quote.startswith("**First pass.") else ''
            out.append("<blockquote%s><p>%s</p></blockquote>" % (cls, inline(quote)))
            continue

        # --- lists --------------------------------------------------------
        if re.match(r"^\s*[-*]\s+\S", ln) or re.match(r"^\s*\d+\.\s+\S", ln):
            ordered = bool(re.match(r"^\s*\d+\.\s", ln))
            items = []
            while i < n:
                mm = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", lines[i])
                if not mm:
                    break
                items.append(mm.group(1).strip())
                i += 1
            if mode == "kds":
                out.append(render_kds(items))
            elif mode == "reading":
                out.append(render_reading(items))
            else:
                tag = "ol" if ordered else "ul"
                out.append("<%s>%s</%s>"
                           % (tag, "".join("<li>%s</li>" % inline(x) for x in items), tag))
            continue

        # --- paragraph -----------------------------------------------------
        if ln.strip():
            buf = []
            while (i < n and lines[i].strip()
                   and not lines[i].startswith(("```", "#", "|", ">"))
                   and not re.match(r"^\s*(?:[-*]|\d+\.)\s+\S", lines[i])
                   and not re.match(r"^-{3,}\s*$", lines[i])):
                buf.append(lines[i].strip())
                i += 1
            if buf:
                out.append("<p>%s</p>" % inline(" ".join(buf)))
                continue
        i += 1

    close_sub()
    return title, nav, "".join(out)


# ---------------------------------------------------------------- assemble

def main():
    sections = []
    for idx, (fn, kicker) in enumerate(FILES, 1):
        with open(os.path.join(SRC, fn), encoding="utf-8") as f:
            md = f.read()
        sec_id = "sec-%d" % idx
        title, nav, body = convert(md, idx, sec_id, kicker)
        sections.append({"id": sec_id, "n": idx, "kicker": kicker,
                         "title": title, "nav": nav, "body": body})

    nav_html = []
    for s in sections:
        items = "".join(
            '<li class="%s"><a href="#%s" data-nav="%s">%s</a></li>'
            % ("nav-minor" if it["minor"] else ("nav-deep" if it["sub"] else ""),
               it["id"], it["id"], html.escape(it["text"]))
            for it in s["nav"])
        nav_html.append(
            '<details class="nav-sec" data-sec="%s"%s>'
            '<summary><span class="nav-num">%02d</span>'
            '<span class="nav-kicker">%s</span>'
            '<span class="nav-title">%s</span></summary>'
            '<ul>%s</ul></details>'
            % (s["id"], " open" if s["n"] == 1 else "", s["n"],
               html.escape(s["kicker"]), html.escape(s["title"]), items))

    body_html = "".join(
        '<article class="section" id="%s-wrap" data-section="%s">%s</article>'
        % (s["id"], s["id"], s["body"]) for s in sections)

    doc = TEMPLATE.replace("{{NAV}}", "".join(nav_html))
    doc = doc.replace("{{BODY}}", body_html)
    with open(os.path.join(HERE, "diagrams", "ownership.html"), encoding="utf-8") as f:
        doc = doc.replace("{{OWNERSHIP}}", link_refs(f.read()))
    doc = doc.replace("{{TOC_JSON}}", json.dumps(
        [{"id": s["id"], "n": s["n"], "title": s["title"]} for s in sections]))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    print("wrote %s  (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024.0))
    for s in sections:
        print("  %02d %-10s %-62s %2d headings" % (s["n"], s["kicker"], s["title"], len(s["nav"])))


TEMPLATE = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()

if __name__ == "__main__":
    main()
