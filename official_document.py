"""Extract government document text, excluding demonstrably non-document UI."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse


class _Node:
    def __init__(self, tag='', attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []


class _Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _nodes(node):
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _nodes(child)


def _text(node, excluded_classes=frozenset()):
    if isinstance(node, str):
        return node
    if node.tag in {'script', 'style', 'nav', 'header', 'footer', 'aside'} or excluded_classes.intersection(node.attrs.get('class', '').split()):
        return ''
    return ' '.join(_text(child, excluded_classes) for child in node.children)


def _finlex_text(html):
    chunks = [json.loads(match.group(1))[1] for match in re.finditer(r'self\.__next_f\.push\((\[\s*1\s*,\s*".*?"\s*\])\)', html, re.S)]
    records = {}
    for line in ''.join(chunks).splitlines():
        match = re.match(r'^([0-9a-f]+):(.*)', line)
        if match:
            try:
                records[match[1]] = json.loads(match[2])
            except ValueError:
                # Import, diagnostic and non-JSON text records are not rendered
                # statute nodes. If a statute references one, fail below.
                pass
    sections = []

    def find(value):
        if isinstance(value, list):
            if len(value) > 3 and value[0] == '$' and isinstance(value[3], dict):
                props = value[3]
                if props.get('lang') == 'fi' and 'akomaNtoso' in props.get('className', ''):
                    sections.append(value)
                    return
            for child in value:
                find(child)
        elif isinstance(value, dict):
            for child in value.values():
                find(child)

    for value in records.values():
        find(value)

    def render(value, seen=frozenset()):
        if isinstance(value, str):
            reference = re.fullmatch(r'\$(?:L)?([0-9a-f]+)', value)
            if reference:
                key = reference[1]
                if key in seen or key not in records:
                    raise ValueError('Finlex statute contains an unresolved document reference')
                return render(records[key], seen | {key})
            return value if not value.startswith('$') else ''
        if isinstance(value, list):
            if len(value) > 3 and value[0] == '$' and isinstance(value[3], dict):
                if value[1] in {'script', 'style', 'button'}:
                    return ''
                return render(value[3].get('children', []), seen)
            return ' '.join(render(child, seen) for child in value)
        if isinstance(value, dict):
            return render(value.get('children', []), seen)
        return ''

    if not sections:
        raise ValueError('Finlex did not return the Finnish statute body')
    # Repeated React records can reference the same section. Preserve document
    # order within each section, but discard duplicate rendered sections.
    texts = list(dict.fromkeys(' '.join(render(section).split()) for section in sections))
    return ' '.join(texts)


def extract_official_document(html: str, source_url: str) -> str | None:
    host = (urlparse(source_url).hostname or '').lower()
    if host.endswith('finlex.fi') and 'self.__next_f.push' in html:
        return _finlex_text(html)
    if host not in {'www.ris.bka.gv.at', 'ris.bka.gv.at', 'guichet.public.lu', 'etalonline.by', 'www.etalonline.by', 'consumator.gov.md'}:
        return None
    document = _Document(html)
    nodes = list(_nodes(document.root))
    if host == 'consumator.gov.md':
        articles = [node for node in nodes if node.tag == 'article' and node.attrs.get('data-history-node-id')]
        bodies = [node for article in articles for node in _nodes(article)
                  if 'field--name-body' in node.attrs.get('class', '').split()]
        if not bodies or not ' '.join(_text(node) for node in bodies).strip():
            raise ValueError('Moldova did not return its article body')
        # Drupal counters and reading-time badges are outside this field.
        return ' '.join(_text(node) for node in bodies)
    if host.endswith('ris.bka.gv.at'):
        bodies = [node for node in nodes if 'documentContent' in node.attrs.get('class', '').split()]
        if not bodies:
            raise ValueError('RIS did not return its legal document body')
        return ' '.join(_text(node) for node in bodies)
    if host == 'guichet.public.lu':
        bodies = [node for node in nodes if node.tag == 'main']
        if not bodies:
            raise ValueError('Guichet did not return its guidance body')
        return ' '.join(_text(node, frozenset({'cmp-hours'})) for node in bodies)
    bodies = [node for node in nodes if node.attrs.get('id') == 'doc-content-outline-root']
    if not bodies or not ' '.join(_text(node) for node in bodies).strip():
        raise ValueError('ETALON returned a document shell without legal text')
    return ' '.join(_text(node) for node in bodies)
