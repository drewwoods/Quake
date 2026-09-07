#!/usr/bin/env python3
"""Shared builder for the docs/architecture HTML guides.

Each guide is a directory with sections/*.md, a template.html and a thin
build.py that calls build() with a Doc config. Stdlib only. Implements the
markdown subset the sources actually use: headings, paragraphs, fenced code,
inline code, bold/italic, links, bullet/numbered lists, tables, blockquotes,
horizontal rules.

Plus Quake-specific transforms:
  * WinQuake/file.c:NNN[-MMM]  ->  link to upstream id-Software/Quake
  * ``` fences               ->  <figure class="code"> with a ref header bar
  * "## Call graph" fence     ->  nested collapsible <details> tree
  * "## Key data structures"  ->  table
  * "## Further reading"      ->  link list
  * [text](frame:sec-5)       ->  cross-doc link, anchor checked at build time
  * ::: plate path caption   ->  local image with a Markdown caption
  * {code}/{quoted}/{inferred} -> inline evidence labels (outside code spans)
"""

import html
import json
import os
import re

# Per-build state, set by build() from the Doc config. Module-level because the
# render helpers below are plain functions that all need to see the same paths.
HERE = ""     # the guide's directory; the generated HTML lands here
SRC = ""      # HERE/sections
OUT = ""      # the generated HTML file
XREFS = {}    # scheme -> path of another guide's HTML, relative to HERE
XREF_USED = []  # (scheme, anchor) pairs recorded for the anchor check

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

GH = "https://github.com/id-Software/Quake/blob/master/WinQuake/"


# ---------------------------------------------------------------- refs

# C/header/assembly refs: WinQuake/foo.c:12-34 | WinQuake/foo.s:12 | WinQuake/foo.h
REF_QUALIFIED = re.compile(r"WinQuake/([A-Za-z0-9_]+\.[chs])(?::(\d+)(?:-(\d+))?)?")
# bare foo.c:12 — only used inside call-graph trees, where it is unambiguous
REF_BARE = re.compile(r"\b([A-Za-z0-9_]+\.[chs]):(\d+)(?:-(\d+))?")


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
EVIDENCE = re.compile(r"\{(code|quoted|inferred)\}")
EVIDENCE_LABELS = {"code": "Code", "quoted": "Source", "inferred": "Inference"}


def inline(text, spans=None):
    """Markdown inline -> HTML. Input is raw (unescaped) markdown.

    Link labels are re-entered recursively. `spans` carries the caller's code
    spans into that recursion so a label like [`foo.c`](url) still resolves its
    \x00 placeholders; only the outermost call stashes and unstashes them.
    """
    top = spans is None
    if top:
        spans = []

        def stash(m):
            spans.append(m.group(1))
            return "\x00%d\x00" % (len(spans) - 1)

        text = CODE_SPAN.sub(stash, text)

    links = []

    def stash_link(m):
        label, url = m.group(1), m.group(2)
        external = re.match(r"https?://", url)
        cls = ""
        # Cross-doc reference: "frame:sec-5" -> ../life-of-a-frame/....html#sec-5.
        # The anchor is verified against the target guide at the end of build().
        scheme = url.split(":", 1)[0]
        if scheme in XREFS:
            anchor = url.split(":", 1)[1]
            XREF_USED.append((scheme, anchor))
            url = XREFS[scheme] + ("#" + anchor if anchor else "")
            cls = ' class="xref"'
        elif not external and not url.startswith("#"):
            url = os.path.relpath(os.path.join(SRC, url), HERE)
        links.append('<a%s%s href="%s">%s</a>'
                     % (cls,
                        ' target="_blank" rel="noopener"' if external else '',
                        html.escape(url, quote=True), inline(label, spans)))
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
    text = EVIDENCE.sub(lambda m: '<span class="ev ev-%s">%s</span>'
                        % (m.group(1), EVIDENCE_LABELS[m.group(1)]), text)

    def unstash(m):
        body = link_refs(html.escape(spans[int(m.group(1))]))
        return "<code>%s</code>" % body

    text = re.sub(r"\x01(\d+)\x01", lambda m: links[int(m.group(1))], text)
    if top:
        text = re.sub(r"\x00(\d+)\x00", unstash, text)
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


def render_plate(path, caption):
    """Reference archive images in place; captions carry description and credit."""
    source = os.path.normpath(os.path.join(SRC, path))
    if not os.path.isfile(source):
        raise ValueError("Plate image not found: %s" % path)
    url = html.escape(os.path.relpath(source, HERE), quote=True)
    description, separator, credit = caption.partition(" | ")
    if separator:
        caption = credit
    alt = MD_LINK.sub(lambda m: m.group(1), description).replace("`", "").replace("*", "")
    return ('<figure class="plate"><a href="%s">'
            '<img src="%s" alt="%s" loading="lazy" decoding="async"></a>'
            '<figcaption>%s</figcaption></figure>'
            % (url, url, html.escape(alt, quote=True), inline(caption)))


def render_code(code, lang, ref, folded=False, idx=0):
    label = ref_link_html(ref) if ref else html.escape(lang or "listing")
    tag = {"c": "C", "asm": "ASM"}.get(lang, "TEXT")
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

        # --- archive plates; fail early on missing local assets ----------
        plate = re.fullmatch(r"::: plate (\S+) (.+)", ln)
        if plate:
            out.append(render_plate(plate.group(1), plate.group(2)))
            i += 1
            continue

        # --- authored, accessible diagrams ------------------------------
        diagram = re.fullmatch(r"::: diagram ([a-z0-9-]+)", ln)
        if diagram:
            with open(os.path.join(HERE, "diagrams", diagram.group(1) + ".html"),
                      encoding="utf-8") as f:
                out.append(link_refs(f.read()))
            i += 1
            continue

        if ln.startswith("::: "):
            raise ValueError("Unknown or malformed directive: %s" % ln)

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
            cls = ''
            # A blockquote opening with a bold label is a labelled block: an
            # archive quote ("**.plan.**", "**Abrash, ch. 64.**") or an aside
            # ("**Pentium FDIV bug.**"). Both take the same label treatment;
            # an unlabelled blockquote stays an ordinary inline quotation.
            if quote.startswith("**First pass."):
                cls = ' class="first-pass"'
            elif re.match(r"\*\*[^*]+\*\*", quote):
                cls = ' class="era"'
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
                   and not lines[i].startswith(("```", "#", "|", ">", "::: "))
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

class Doc(object):
    """One guide: where its sources live and what the template needs.

    files   [(section filename, short kicker shown in the nav), ...]
    extra   {template placeholder: fragment path relative to the guide dir}
    xrefs   {scheme: other guide's HTML, relative to the guide dir}
    """

    def __init__(self, here, out, files, template="template.html",
                 extra=None, xrefs=None):
        self.here = here
        self.out = out
        self.files = files
        self.template = template
        self.extra = extra or {}
        self.xrefs = xrefs or {}


ID_ATTR = re.compile(r'id="([^"]+)"')


def check_xrefs(doc):
    """Warn about frame:anchor links whose target heading no longer exists.

    Cross-doc anchors are the one link class nothing else catches: the target
    slug is generated from another guide's heading text, so an innocent
    rewording there silently breaks every inbound link.
    """
    for scheme, target in doc.xrefs.items():
        wanted = set(a for s, a in XREF_USED if s == scheme and a)
        if not wanted:
            continue
        path = os.path.join(doc.here, target)
        if not os.path.exists(path):
            print("  xref: %s: target %s not built yet, %d anchor(s) unchecked"
                  % (scheme, target, len(wanted)))
            continue
        with open(path, encoding="utf-8") as f:
            have = set(ID_ATTR.findall(f.read()))
        for a in sorted(wanted - have):
            print("  xref: %s:%s -> no such anchor in %s" % (scheme, a, target))


def build(doc):
    global HERE, SRC, OUT, XREFS
    HERE, SRC = doc.here, os.path.join(doc.here, "sections")
    OUT = os.path.join(doc.here, doc.out)
    XREFS = doc.xrefs
    del XREF_USED[:]
    _slugs.clear()
    _code_seq[0] = 0

    template = open(os.path.join(doc.here, doc.template), encoding="utf-8").read()

    # Shared look and behaviour, inlined so guides open over file://; plates
    # remain local sibling assets. Injected verbatim: unlike the
    # markdown fragments below, CSS and JS must not go through link_refs().
    for placeholder, asset in (("{{BASE_CSS}}", "base.css"), ("{{BASE_JS}}", "base.js")):
        with open(os.path.join(ASSETS, asset), encoding="utf-8") as f:
            template = template.replace(placeholder, f.read().rstrip("\n"))

    sections = []
    for idx, (fn, kicker) in enumerate(doc.files, 1):
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

    out = template.replace("{{NAV}}", "".join(nav_html))
    out = out.replace("{{BODY}}", body_html)
    for placeholder, frag in doc.extra.items():
        with open(os.path.join(doc.here, frag), encoding="utf-8") as f:
            out = out.replace(placeholder, link_refs(f.read()))
    out = out.replace("{{TOC_JSON}}", json.dumps(
        [{"id": s["id"], "n": s["n"], "title": s["title"]} for s in sections]))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    print("wrote %s  (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024.0))
    for s in sections:
        print("  %02d %-10s %-62s %2d headings" % (s["n"], s["kicker"], s["title"], len(s["nav"])))
    check_xrefs(doc)
