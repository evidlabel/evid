"""Pure JavaScript helpers in the GUI page (evid/web/page.html), run in node."""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")
FUNCS = [
    "splitTags",
    "filterDocs",
    "tagCounts",
    "completeTags",
    "rangeSelect",
    "labelPreview",
    "searchSubmit",
    "searchDone",
    "shortUuid",
    "highlight",
    "labKey",
    "labCall",
    "escHtml",
    "typHighlight",
    "keepOrder",
    "isSaveKey",
]


def js_function(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i : k + 1]
    raise ValueError(name)


@pytest.fixture(scope="module")
def js():
    src = (resources.files("evid.web") / "page.html").read_text("utf-8")
    lib = "\n".join(js_function(src, n) for n in FUNCS)
    rx = src[src.index("const TYP_RX") :]
    lib = rx[: rx.index("\n") + 1] + lib

    def run(expr: str):
        prog = lib + f"\nprocess.stdout.write(JSON.stringify((() => {{ {expr} }})()));"
        out = subprocess.run(
            [NODE, "-e", prog], capture_output=True, text=True, check=True
        ).stdout
        return json.loads(out)

    return run


DOCS = json.dumps(
    [
        {"uuid": "aaa111", "label": "Hansen ruling", "tags": ["c.psych", "c.court"]},
        {"uuid": "bbb222", "label": "Letter", "tags": ["c.court"]},
        {"uuid": "ccc333", "label": "Notes", "tags": []},
    ]
)


def test_split_tags(js):
    assert js("return splitTags(' a, b ,, c ');") == ["a", "b", "c"]
    assert js("return splitTags(null);") == []


def test_filter_text_and_tags_are_anded(js):
    f = f"const D = {DOCS};"
    assert js(f + "return filterDocs(D, '', new Set()).map(d => d.uuid);") == [
        "aaa111",
        "bbb222",
        "ccc333",
    ]
    assert js(f + "return filterDocs(D, 'LETT', new Set()).map(d => d.uuid);") == [
        "bbb222"
    ]
    assert js(f + "return filterDocs(D, 'ccc', new Set()).map(d => d.uuid);") == [
        "ccc333"
    ]
    assert js(
        f + "return filterDocs(D, '', new Set(['c.court'])).map(d => d.uuid);"
    ) == ["aaa111", "bbb222"]
    assert js(
        f
        + "return filterDocs(D, '', new Set(['c.court', 'c.psych'])).map(d => d.uuid);"
    ) == ["aaa111"]
    assert (
        js(f + "return filterDocs(D, 'letter', new Set(['c.psych'])).map(d => d.uuid);")
        == []
    )


def test_tag_counts_sorted_with_registry_extras(js):
    assert js(f"return tagCounts({DOCS}, ['c.empty']);") == [
        ["c.court", 2],
        ["c.empty", 0],
        ["c.psych", 1],
    ]


def test_complete_last_token(js):
    all_ = json.dumps(["c.psych", "c.court", "c.costs"])
    r = js(f"return completeTags('c.psych, co', {all_});")
    assert r["head"] == "c.psych, " and r["options"] == ["c.costs", "c.court"]
    assert js(f"return completeTags('', {all_}).options;") == [
        "c.costs",
        "c.court",
        "c.psych",
    ]
    assert "c.psych" not in js(f"return completeTags('c.psych, ', {all_}).options;")


def test_range_select(js):
    assert js("return rangeSelect(['a','b','c','d'], 'c', 'a');") == ["a", "b", "c"]
    assert js("return rangeSelect(['a','b'], 'zz', 'b');") == ["b"]


def test_label_preview(js):
    out = js(
        "return labelPreview({section: 'Intro', page: '4', text: 'Words', note: 'mine'});"
    )
    assert out == "§ Intro\np. 4\nWords\n\n[note] mine"


def test_search_queue_runs_only_the_latest(js):
    out = js("""
      const q = {busy: false, queued: null};
      const a = searchSubmit(q, 'a');      // runs
      const b = searchSubmit(q, 'b');      // queued
      const c = searchSubmit(q, 'c');      // replaces b
      const n1 = searchDone(q);            // a done -> c
      const n2 = searchDone(q);            // c done -> idle
      return [a, b, c, n1, n2, q.busy];
    """)
    assert out == ["a", None, None, "c", None, False]


def test_short_uuid(js):
    assert js("return shortUuid('0123456789abcdef0123');") == "01234567…cdef0123"
    assert js("return shortUuid('short');") == "short"


def test_highlight(js):
    assert js("return highlight('A cat and a CAT', 'cat', false);") == [
        ["A ", False],
        ["cat", True],
        [" and a ", False],
        ["CAT", True],
    ]
    assert js("return highlight('x.y', '.', false);") == [
        ["x", False],
        [".", True],
        ["y", False],
    ]
    assert js("return highlight('a1 b22', '\\\\d+', true);") == [
        ["a", False],
        ["1", True],
        [" b", False],
        ["22", True],
    ]
    assert js("return highlight('abc', '(', true);") == [["abc", False]]
    assert js("return highlight('abc', '', false);") == [["abc", False]]


def test_lab_key(js):
    assert (
        js("return labKey('The claimant\\'s working capacity', []);")
        == "the-claimant-s"
    )
    assert (
        js("return labKey('Kommunens afgørelse', ['kommunens-afgoerelse']);")
        == "kommunens-afgoerelse-2"
    )
    assert js("return labKey('', []);") == "label"


def test_lab_call_escapes(js):
    assert (
        js("""return labCall('k', 'He said "no"\\nback\\\\slash', '');""")
        == '#lab("k", "He said \\"no\\" back\\\\slash", "")'
    )


def test_typ_highlight_marks_lab_parts(js):
    html = js("""return typHighlight('x #lab("k-1", "a \\\\"q\\\\" <b>", "n") y');""")
    assert '<span class="lab">#lab</span>' in html
    assert '<span class="key">"k-1"</span>' in html
    assert '<span class="quote">"a \\"q\\" &lt;b&gt;"</span>' in html
    assert '<span class="note">"n"</span>' in html
    assert html.startswith("x ") and html.endswith(" y")


def test_typ_highlight_other_tokens(js):
    src = '#import "@preview/labtyp:0.1.0": lab\\n= Title\\n== Page 3\\n// c\\n#lab("k", "two-arg")'
    html = js(f"return typHighlight('{src}');")
    assert (
        '<span class="hash">#import</span>' in html
        and '<span class="str">"@preview/labtyp:0.1.0"</span>' in html
    )
    assert (
        '<span class="head">= Title</span>' in html
        and '<span class="page">== Page 3</span>' in html
    )
    assert (
        '<span class="com">// c</span>' in html
        and '<span class="quote">"two-arg"</span>' in html
    )
    assert (
        js("return typHighlight('plain <text> & more');")
        == "plain &lt;text&gt; &amp; more"
    )


def test_keep_order_on_reload(js):
    out = js(
        """return keepOrder(['a', 'b', 'c'], [{uuid: 'c'}, {uuid: 'n'}, {uuid: 'a'}]).map(d => d.uuid);"""
    )
    assert out == ["n", "a", "c"]  # new first, known keep their places, gone dropped


def test_is_save_key(js):
    cases = [
        ("{ctrlKey: true, key: 's'}", True),
        ("{ctrlKey: true, key: 'S', shiftKey: true}", True),  # Caps Lock / Shift
        ("{metaKey: true, code: 'KeyS', key: 'ß'}", True),  # another layout
        ("{key: 's'}", False),
        ("{ctrlKey: true, altKey: true, key: 's'}", False),
        ("{ctrlKey: true, key: 'l'}", False),
    ]
    for ev, want in cases:
        assert js(f"return isSaveKey({ev});") is want, ev
