#!/usr/bin/env python
#
"""
Digest a saved web page into a short Markdown summary for review.

A rendered banking page is over a megabyte of markup, most of it scripts,
styles, inline icons and JSON packed into data attributes. This drops all of
that and writes what matters when fixing scraper selectors:

- the page title, and the size before and after stripping
- dialogs ('role="dialog"' or 'aria-modal'), and whether each looks hidden
- links, buttons and form fields, with their ids, classes and labels
- repeated structures (three or more siblings with the same tag and
  classes), such as table rows, with an outline of one example of each
- the most common ids and classes
- an indented outline of the whole page with its text

Link hrefs are reduced to their path and query parameter names; parameter
values are session tokens and noise.

Usage:
    uv run tools/digest_page.py PAGE.html [PAGE.html ...]
    uv run tools/digest_page.py --stdout PAGE.html

By default each digest is written next to its page as '<stem>.digest.md'.
"""

# system imports
import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

# 3rd party imports
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

# Tags whose contents never matter for selector work.
STRIP_TAGS = ("script", "style", "noscript", "template", "link", "meta")

# Attribute values longer than this are replaced by their length. BofA packs
# page copy and module options into data attributes as JSON.
MAX_ATTR_LEN = 120

# Attributes shown in outline lines, in this order, when present.
HINT_ATTRS = ("role", "aria-label", "type", "name", "data-testid", "href")

TEXT_LEN = 80
MIN_REPEAT = 3

# Digits and long hex runs in ids and classes ('account-3_id', 'txn-<sha256>')
# are normalized so that sibling rows share one signature.
_HEX_RE = re.compile(r"[0-9a-fA-F]{16,}")
_NUM_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


####################################################################
#
def load_page(path: Path) -> BeautifulSoup:
    """
    Parse a saved page and strip everything that is not structure or text.

    Args:
        path: The saved HTML file.

    Returns:
        The parsed document with scripts, styles, comments and icon markup
        removed, inline styles dropped, and long attribute values shortened.
    """
    soup = BeautifulSoup(path.read_bytes(), "lxml")
    for el in soup.find_all(STRIP_TAGS):
        el.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for svg in soup.find_all("svg"):
        svg.clear()
        svg.attrs = {k: v for k, v in svg.attrs.items() if k == "class"}
    for el in soup.find_all(True):
        el.attrs.pop("style", None)
        for key, value in list(el.attrs.items()):
            if isinstance(value, str) and len(value) > MAX_ATTR_LEN:
                el.attrs[key] = f"<{len(value)} chars>"
    return soup


####################################################################
#
def attr(el: Tag, name: str) -> str:
    """Return an attribute as a single string, '' when absent."""
    value = el.get(name)
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(value)
    return str(value)


####################################################################
#
def classes(el: Tag) -> list[str]:
    """Return the element's classes as a list."""
    value = el.get("class")
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    return list(value)


####################################################################
#
def normalize(token: str) -> str:
    """Replace long hex runs and digit runs so numbered siblings match."""
    return _NUM_RE.sub("N", _HEX_RE.sub("HEX", token))


####################################################################
#
def clip(text: str, length: int = TEXT_LEN) -> str:
    """Collapse whitespace and truncate to length characters."""
    text = _WS_RE.sub(" ", text).strip()
    return text if len(text) <= length else text[: length - 3] + "..."


####################################################################
#
def selector(el: Tag) -> str:
    """Return a CSS-style label for the element: tag#id.class.class."""
    out = el.name
    if el_id := attr(el, "id"):
        out += f"#{el_id}"
    for cls in classes(el):
        out += f".{cls}"
    return out


####################################################################
#
def signature(el: Tag) -> str:
    """
    Return a label that numbered or hashed siblings share.

    Uses the tag and normalized classes; when the element has no classes the
    normalized id stands in, so 'li#item-1' and 'li#item-2' match.
    """
    cls = sorted({normalize(c) for c in classes(el)})
    if cls:
        return el.name + "".join(f".{c}" for c in cls)
    if el_id := attr(el, "id"):
        return f"{el.name}#{normalize(el_id)}"
    return el.name


####################################################################
#
def short_href(href: str) -> str:
    """Reduce an href to its path plus the names of its query parameters."""
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return href
    parts = urlsplit(href)
    names = [k for k, _ in parse_qsl(parts.query, keep_blank_values=True)]
    host = parts.netloc
    out = f"{host}{parts.path}" if host else parts.path
    if names:
        out += "?" + "&".join(names)
    return out


####################################################################
#
def looks_hidden(el: Tag) -> bool:
    """
    Return True when the element or an ancestor is marked hidden in markup.

    Static markup cannot show computed CSS, so this is a hint: the 'hidden'
    attribute, 'aria-hidden="true"', or a class named 'hidden'.
    """
    node: Tag | None = el
    while node is not None and node.name != "[document]":
        if node.has_attr("hidden") or attr(node, "aria-hidden") == "true":
            return True
        if "hidden" in classes(node):
            return True
        node = node.parent
    return False


####################################################################
#
def own_text(el: Tag) -> str:
    """Return the text directly inside the element, not in its children."""
    return clip(
        " ".join(str(c) for c in el.children if isinstance(c, NavigableString))
    )


####################################################################
#
def hints(el: Tag) -> str:
    """Return the outline annotations for an element."""
    out = []
    for name in HINT_ATTRS:
        value = attr(el, name)
        if not value:
            continue
        if name == "href":
            value = short_href(value)
        out.append(f"{name}={clip(value, 60)!r}")
    if el.name in ("input", "select", "textarea") and attr(el, "placeholder"):
        out.append(f"placeholder={clip(attr(el, 'placeholder'), 40)!r}")
    return f" [{' '.join(out)}]" if out else ""


####################################################################
#
def child_tags(el: Tag) -> list[Tag]:
    """Return the element's direct child elements."""
    return [c for c in el.children if isinstance(c, Tag)]


####################################################################
#
def outline(el: Tag, depth: int = 0, max_lines: int | None = None) -> list[str]:
    """
    Render an indented outline of el and its descendants.

    A chain of wrappers that each have one child element, no text and no id is
    folded onto a single line joined by ' > '. A run of siblings with the same
    signature shows its first two members and a count of the rest.

    Args:
        el:        The root of the outline.
        depth:     Indent level of el.
        max_lines: Stop after this many lines, when given.

    Returns:
        The outline lines.
    """
    lines: list[str] = []

    def walk(node: Tag, level: int) -> None:
        if max_lines is not None and len(lines) >= max_lines:
            return
        chain = [node]
        while True:
            kids = child_tags(chain[-1])
            tail = chain[-1]
            if (
                len(kids) == 1
                and not own_text(tail)
                and not attr(tail, "id")
                and not hints(tail)
            ):
                chain.append(kids[0])
            else:
                break
        last = chain[-1]
        label = " > ".join(selector(n) for n in chain)
        text = own_text(last)
        line = "  " * level + label + hints(last)
        if text:
            line += f'  "{text}"'
        lines.append(line)

        kids = child_tags(last)
        i = 0
        while i < len(kids):
            sig = signature(kids[i])
            j = i
            while j < len(kids) and signature(kids[j]) == sig:
                j += 1
            run = j - i
            for kid in kids[i : i + min(run, 2)]:
                walk(kid, level + 1)
            if run > 2:
                lines.append(
                    "  " * (level + 1) + f"... {run - 2} more {sig} siblings"
                )
            i = j

    walk(el, depth)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
    return lines


####################################################################
#
def find_repeats(body: Tag) -> list[tuple[str, str, int, int, Tag]]:
    """
    Find groups of three or more same-signature siblings.

    Returns:
        (child signature, parent signature, total count, number of parents,
        first example) tuples, largest groups first.
    """
    groups: dict[tuple[str, str], list[Tag]] = {}
    parents: Counter[tuple[str, str]] = Counter()
    for parent in [body, *body.find_all(True)]:
        sigs = Counter(signature(c) for c in child_tags(parent))
        for sig, count in sigs.items():
            if count < MIN_REPEAT:
                continue
            key = (sig, signature(parent))
            members = [c for c in child_tags(parent) if signature(c) == sig]
            groups.setdefault(key, []).extend(members)
            parents[key] += 1
    out = [
        (sig, psig, len(members), parents[(sig, psig)], members[0])
        for (sig, psig), members in groups.items()
    ]
    out.sort(key=lambda g: g[2], reverse=True)
    return out


####################################################################
#
def interactive_lines(body: Tag) -> dict[str, list[str]]:
    """
    List links, buttons and form fields, grouped by normalized selector.

    Elements that share a normalized selector, attribute hints and hidden
    state are one line, showing the first element's text and a count. So the
    View/Edit link on every transaction row is one line, not hundreds.

    Returns:
        A dict of section name to lines.
    """
    found: dict[str, dict[str, tuple[str, int]]] = {
        "Links": {},
        "Buttons": {},
        "Form fields": {},
    }
    for el in body.find_all(True):
        role = attr(el, "role")
        if el.name == "a" or role == "link":
            section = "Links"
        elif el.name == "button" or role in ("button", "tab", "menuitem"):
            section = "Buttons"
        elif el.name in ("input", "select", "textarea"):
            section = "Form fields"
        else:
            continue
        key = f"`{normalize(selector(el))}`{hints(el)}"
        if looks_hidden(el):
            key += "  (hidden?)"
        text, count = found[section].get(key, (clip(el.get_text(" "), 60), 0))
        found[section][key] = (text, count + 1)

    out: dict[str, list[str]] = {}
    for name, groups in found.items():
        lines = []
        for key, (text, count) in groups.items():
            line = key
            if count > 1:
                line += f"  x{count}, first:"
            if text:
                line += f'  "{text}"'
            lines.append(line)
        out[name] = lines
    return out


####################################################################
#
def digest(path: Path, max_outline: int = 3000) -> str:
    """
    Build the Markdown digest for one saved page.

    Args:
        path:        The saved HTML file.
        max_outline: Maximum number of lines in the page outline section.

    Returns:
        The digest as Markdown text.
    """
    raw_size = path.stat().st_size
    soup = load_page(path)
    title = clip(soup.title.get_text() if soup.title else "", 200)
    body = soup.body or soup
    stripped_size = len(str(body))

    out = [
        f"# Digest: {path.name}",
        "",
        f"- Title: {title or '(none)'}",
        f"- Size: {raw_size:,} bytes saved, {stripped_size:,} after stripping",
        "- Hidden markers are hints from markup only; computed CSS is unknown.",
        "",
    ]

    out += ["## Dialogs", ""]
    dialogs = [
        el
        for el in body.find_all(True)
        if attr(el, "role") in ("dialog", "alertdialog")
        or attr(el, "aria-modal") == "true"
    ]
    if not dialogs:
        out.append("(none)")
    for el in dialogs:
        state = "hidden?" if looks_hidden(el) else "possibly visible"
        out += [f"### `{selector(el)}` ({state})", "", "```"]
        out += outline(el, max_lines=80)
        out += ["```", ""]
    out.append("")

    for name, lines in interactive_lines(body).items():
        out += [f"## {name} ({len(lines)})", ""]
        out += [f"- {ln}" for ln in lines[:200]] or ["(none)"]
        if len(lines) > 200:
            out.append(f"- ... {len(lines) - 200} more")
        out.append("")

    out += ["## Repeated structures", ""]
    repeats = find_repeats(body)
    if not repeats:
        out.append("(none)")
    for sig, psig, count, nparents, example in repeats[:25]:
        where = f"under `{psig}`"
        if nparents > 1:
            where += f" ({nparents} parents)"
        out += [f"### `{sig}` x{count} {where}", "", "```"]
        out += outline(example, max_lines=40)
        out += ["```", ""]
    out.append("")

    ids: Counter[str] = Counter()
    cls: Counter[str] = Counter()
    for el in body.find_all(True):
        if el_id := attr(el, "id"):
            ids[normalize(el_id)] += 1
        for c in classes(el):
            cls[normalize(c)] += 1
    out += ["## Most common ids (normalized)", ""]
    out += [f"- `{k}` x{n}" for k, n in ids.most_common(40)] or ["(none)"]
    out += ["", "## Most common classes (normalized)", ""]
    out += [f"- `{k}` x{n}" for k, n in cls.most_common(60)] or ["(none)"]
    out.append("")

    out += ["## Page outline", "", "```"]
    lines = outline(body, max_lines=max_outline)
    out += lines
    if len(lines) >= max_outline:
        out.append(f"... truncated at {max_outline} lines")
    out += ["```", ""]
    return "\n".join(out)


####################################################################
#
def digest_path(path: Path) -> Path:
    """Return where the digest for a page is written."""
    return path.with_name(f"{path.stem}.digest.md")


####################################################################
#
def main() -> int:
    """Digest each page named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pages", nargs="+", type=Path, help="saved HTML files")
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print digests instead of writing <stem>.digest.md files",
    )
    parser.add_argument(
        "--max-outline",
        type=int,
        default=3000,
        help="maximum lines in the page outline (default 3000)",
    )
    args = parser.parse_args()

    for page in args.pages:
        text = digest(page, max_outline=args.max_outline)
        if args.stdout:
            sys.stdout.write(text)
        else:
            out = digest_path(page)
            out.write_text(text)
            print(f"{page} -> {out} ({len(text):,} bytes)")
    return 0


########################################################################

if __name__ == "__main__":
    sys.exit(main())
