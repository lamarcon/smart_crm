"""Inventory of the Portuguese interface text in app/static/index.html (test helper).

Static markup gives text nodes and translatable attributes. In the script, string
and template literals are tokenized; template expressions become {pN} slots and
markup inside literals is split into text segments, the same pieces the browser
ends up with as text nodes.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

ATTRS = {"placeholder", "title", "aria-label", "alt"}
LETTER = re.compile(r"[A-Za-zÀ-ÿ]")
PT_HINT = re.compile(r"[À-ÿ]|\b(de|da|do|das|dos|para|com|sem|uma?|não|nenhum|nenhuma|selecione|informe|salvar|excluir|novo|nova|cadastr\w*|registro|usuário|empresa|contato|negócio|orçamento|campo|filtro|etapa|ativo|inativo|todos|todas|cancelar|fechar|voltar|editar|abrir|criar|buscar|adicionar|remover|e|ou|o|a|os|as|em|no|na|ao|à)\b", re.I)


class Markup(HTMLParser):
    def __init__(self, sink, line_offset=0):
        super().__init__(convert_charrefs=True)
        self.sink = sink
        self.skip = 0
        self.line_offset = line_offset

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for name, value in attrs:
            if name in ATTRS and value:
                self.sink(value, "attr", self.line_offset + self.getpos()[0])

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.sink(data, "text", self.line_offset + self.getpos()[0])


def tokenize_js(src, base_line):
    """Yields (kind, value, line) for string/template literals; template values are
    lists of static parts with nested expressions replaced by slots."""
    i, n = 0, len(src)
    last_sig = ""  # last significant char, to tell regex from division

    def line_at(pos):
        return base_line + src.count("\n", 0, pos)

    def read_string(i, quote):
        j = i + 1
        out = []
        while j < n and src[j] != quote:
            if src[j] == "\\":
                out.append(src[j:j + 2]); j += 2; continue
            if src[j] == "\n":
                break
            out.append(src[j]); j += 1
        return "".join(out), j + 1

    def skip_regex(i):
        j = i + 1
        in_class = False
        while j < n:
            c = src[j]
            if c == "\\": j += 2; continue
            if c == "[": in_class = True
            elif c == "]": in_class = False
            elif c == "/" and not in_class: break
            elif c == "\n": return i + 1
            j += 1
        j += 1
        while j < n and src[j].isalpha(): j += 1
        return j

    def read_template(i):
        """Returns (parts, end) where parts alternate text and slot markers; nested
        literals inside expressions are yielded separately."""
        j = i + 1
        text = []
        slot = 0
        nested = []
        while j < n:
            c = src[j]
            if c == "\\":
                text.append(src[j:j + 2]); j += 2; continue
            if c == "`":
                return "".join(text), j + 1, nested
            if c == "$" and j + 1 < n and src[j + 1] == "{":
                depth = 1
                k = j + 2
                start = k
                while k < n and depth:
                    ch = src[k]
                    if ch in "'\"":
                        value, k2 = read_string(k, ch)
                        nested.append(("string", value, line_at(k)))
                        k = k2; continue
                    if ch == "`":
                        value, k2, inner = read_template(k)
                        nested.append(("template", value, line_at(k)))
                        nested.extend(inner)
                        k = k2; continue
                    if ch == "{": depth += 1
                    elif ch == "}": depth -= 1
                    k += 1
                text.append("{p%d}" % slot)
                slot += 1
                j = k
                continue
            text.append(c); j += 1
        return "".join(text), j, nested

    while i < n:
        c = src[i]
        if src.startswith("//", i):
            i = src.find("\n", i); i = n if i < 0 else i; continue
        if src.startswith("/*", i):
            i = src.find("*/", i) + 2; continue
        if c in "'\"":
            value, i2 = read_string(i, c)
            yield "string", value, line_at(i)
            i = i2; last_sig = c; continue
        if c == "`":
            value, i2, nested = read_template(i)
            yield "template", value, line_at(i)
            yield from nested
            i = i2; last_sig = "`"; continue
        if c == "/":
            if last_sig == "" or last_sig in "(,=:[!&|?{};+-*%<>~^\n" or re.search(r"(return|typeof|case)\s*$", src[max(0, i - 8):i]):
                i = skip_regex(i); last_sig = "/"; continue
        if not c.isspace():
            last_sig = c
        i += 1



def _looks_like_interface(item: dict) -> bool:
    key = item["key"]
    if item["kinds"] != ["js-string"]:
        return True
    return bool(re.search(r"[À-ÿ]", key) or re.search(r"[A-Za-z] [A-Za-z]", key) or re.match(r"^[A-ZÀ-Ý][a-zà-ÿ]", key))


def interface_strings(html: str) -> dict[str, int]:
    """Portuguese interface strings mapped to the first line where they appear."""

    lines = html.split("\n")
    script_start = next(k for k, line in enumerate(lines) if line.strip() == "<script>")
    script_end = max(k for k, line in enumerate(lines) if line.strip() == "</script>")
    found: dict[str, dict] = {}

    def add(raw, kind, line):  # noqa: ANN001
        core = re.sub(r"\s+", " ", raw.replace("\\n", " ")).strip()
        core = core.replace("\\'", "'").replace('\\"', '"')
        if not core or not LETTER.search(core) or re.fullmatch(r"(\{p\d+\}\s*)+", core):
            return
        entry = found.setdefault(core, {"key": core, "kinds": set(), "line": line})
        entry["kinds"].add(kind)

    Markup(add).feed("\n".join(lines[:script_start]))
    Markup(add, script_end + 1).feed("\n".join(lines[script_end + 1:]))
    script = "\n".join(lines[script_start + 1:script_end])
    for kind, value, line in tokenize_js(script, script_start + 2):
        if kind == "template" or "<" in value:
            parser = Markup(lambda raw, k, _l, line=line: add(raw, "js-" + k, line))
            try:
                parser.feed(value)
                parser.close()
            except Exception:
                add(value, "js-raw", line)
        else:
            add(value, "js-string", line)
    result = {}
    for item in found.values():
        item["kinds"] = sorted(item["kinds"])
        if _looks_like_interface(item) and PT_HINT.search(item["key"]):
            result[item["key"]] = item["line"]
    return result


