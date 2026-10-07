"""Pure JavaScript helpers in the GUI page (evid/web/page.html), run in node."""

from __future__ import annotations

import json
import re
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
    "openTarget",
    "labKey",
    "escHtml",
    "escAttr",
    "labelHtml",
    "edWordStep",
    "edLineStep",
    "edMove",
    "edListStep",
    "edListMove",
    "pageAt",
    "keepOrder",
    "isSaveKey",
    "selectionText",
    "lineDiff",
    "lineHunks",
    "merge3",
    "mergeFields",
    "freshness",
    "historyChips",
    "agentBadge",
    "noteLine",
    "hitSpan",
    "findAll",
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


def test_open_target(js):
    assert js("return openTarget('');") is None
    assert js("return openTarget('?set=case&doc=u1');") == {
        "slug": "case",
        "uuid": "u1",
        "pane": "label",
    }
    assert js("return openTarget('?set=case&doc=u1&pane=detail');") == {
        "slug": "case",
        "uuid": "u1",
        "pane": "detail",
    }
    assert js("return openTarget('?set=case');") == {
        "slug": "case",
        "uuid": "",
        "pane": "",
    }


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


def test_hit_span(js):
    assert js("return hitSpan({char_start: 4, char_end: 10}, 100);") == {
        "start": 4,
        "end": 10,
    }
    # clamped to the text; a meta hit (no offsets) or an empty span has none
    assert js("return hitSpan({char_start: 95, char_end: 140}, 100);") == {
        "start": 95,
        "end": 100,
    }
    assert js("return hitSpan({uuid: 'u'}, 100);") is None
    assert js("return hitSpan({char_start: 100, char_end: 120}, 100);") is None


def test_find_all(js):
    assert js("return findAll('A cat. a CAT (cat)', 'cat');") == [
        {"start": 2, "end": 5},
        {"start": 9, "end": 12},
        {"start": 14, "end": 17},
    ]
    # literal, not a regex; empty finds nothing; capped
    assert js("return findAll('a.b axb', 'a.b');") == [{"start": 0, "end": 3}]
    assert js("return findAll('abc', '');") == []
    assert js("return findAll('aaaa', 'a', 2).length;") == 2


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


def test_label_html_layers_pages_and_escapes(js):
    html = js(
        """return labelHtml('Hello <world>. Page two is here.', [[0, 1], [15, 2]],
        [{key: 'hw', start: 0, end: 5}],
        [{id: 'a1', start: 2, end: 8}],
        [{key: 'q1', start: 0, end: 20}]);"""
    )
    assert html.startswith('<div class="pageband">— page 1 —</div>')
    assert '<div class="pageband">— page 2 —</div>' in html
    plain = re.sub(r"<[^>]+>", "", html)
    assert "Hello &lt;world&gt;." in plain and "— page 2 —" in plain
    assert '<span data-start="0">' in html and '<span data-start="15">' in html
    # the band is not inside a data-start span, and a crossing quote closes around it
    assert '</span><div class="pageband">— page 2 —</div><span class="mk mk-m"' in html
    # overlap nests machine, then annotation, then human
    assert (
        'data-kind="a" data-id="a1"><span class="mk mk-h" data-kind="h" data-id="hw"'
        in html
    )
    assert js("return pageAt([[0, 1], [15, 2]], 15);") == 2
    assert js("return pageAt([[0, 1], [15, 2]], 3);") == 1


def test_label_cursor_moves_and_shift_extends(js):
    text = "Hello evidence.\nThe municipality did not reply."
    cur = {"at": 0, "anchor": 0}
    cur = js(f"return edMove({text!r}, {cur}, 'ArrowRight', false);")
    assert cur == {"at": 1, "anchor": 1}
    cur = js(f"return edMove({text!r}, {json.dumps(cur)}, 'ArrowRight', true);")
    assert cur == {"at": 2, "anchor": 1}
    cur = js(f"return edMove({text!r}, {json.dumps(cur)}, 'ArrowRight', true);")
    assert cur == {"at": 3, "anchor": 1}
    cur = js(f"return edMove({text!r}, {json.dumps(cur)}, 'ArrowLeft', true);")
    assert cur == {"at": 2, "anchor": 1}
    # a plain arrow drops the selection and moves from the caret
    cur = js(f"return edMove({text!r}, {json.dumps(cur)}, 'ArrowRight', false);")
    assert cur == {"at": 3, "anchor": 3}
    # up from the second line keeps the column; down from the end stays put
    assert js(f"return edLineStep({text!r}, 22, -1);") == 6
    assert js("return edLineStep('ab\\nc', 0, -1);") == 0
    assert js("return edLineStep('ab\\nc', 4, 1);") == 4
    # an empty line still has a place for the caret
    assert js("return edLineStep('\\nab', 1, -1);") == 0
    # end of "Hello" lands at the end of "world"; one column left lands before "d"
    assert js("return edLineStep('Hello\\nworld', 5, 1);") == 11
    assert js("return edLineStep('Hello\\nworld', 4, 1);") == 10
    jumped = js(
        f"return edMove({text!r}, {{at: 0, anchor: 0}}, 'ArrowDown', true, () => 16);"
    )
    assert jumped == {"at": 16, "anchor": 0}


def test_label_cursor_skips_words(js):
    # "Hello, " then "afgørelse" (letters, including ø), then ".\nThe …"
    text = "Hello, afgørelse.\nThe municipality did not reply."
    assert js(f"return edWordStep({text!r}, 0, 1);") == 5
    assert js(f"return edWordStep({text!r}, 5, 1);") == 16
    assert js(f"return edWordStep({text!r}, 16, 1);") == 21
    assert js(f"return edWordStep({text!r}, 2, 1);") == 5
    assert js(f"return edWordStep({text!r}, 6, 1);") == 16
    assert js(f"return edWordStep({text!r}, 21, -1);") == 18
    assert js(f"return edWordStep({text!r}, 18, -1);") == 7
    assert js(f"return edWordStep({text!r}, 7, -1);") == 0
    assert js(f"return edWordStep({text!r}, 16, -1);") == 7
    assert js(f"return edWordStep({text!r}, 0, -1);") == 0
    assert js(f"return edWordStep({text!r}, {len(text)}, 1);") == len(text)
    # digits are a word; the section sign is not
    assert js("return edWordStep('§ 12 a', 0, 1);") == 4
    assert js("return edWordStep('§ 12 a', 4, 1);") == 6
    assert js("return edWordStep('§ 12 a', 6, -1);") == 5
    assert js("return edWordStep('§ 12 a', 5, -1);") == 2
    # a run of spaces is one gap, not a stop
    assert js("return edWordStep('aa   bb', 2, 1);") == 7
    assert js("return edWordStep('aa   bb', 4, -1);") == 0
    assert js("return edWordStep('...', 0, 1);") == 3
    assert js("return edWordStep('', 0, 1);") == 0
    # Shift keeps the anchor; a plain word move drops the selection
    cur = js(
        f"return edMove({text!r}, {{at: 0, anchor: 0}}, 'ArrowRight', true, null, true);"
    )
    assert cur == {"at": 5, "anchor": 0}
    cur = js(
        f"return edMove({text!r}, {json.dumps(cur)}, 'ArrowRight', true, null, true);"
    )
    assert cur == {"at": 16, "anchor": 0}
    cur = js(
        f"return edMove({text!r}, {json.dumps(cur)}, 'ArrowLeft', true, null, true);"
    )
    assert cur == {"at": 7, "anchor": 0}
    cur = js(
        f"return edMove({text!r}, {json.dumps(cur)}, 'ArrowLeft', false, null, true);"
    )
    assert cur == {"at": 0, "anchor": 0}
    # Ctrl does not change a line move
    assert js(
        "return edMove('ab\\ncd', {at: 0, anchor: 0}, 'ArrowDown', false, null, true);"
    ) == {
        "at": 3,
        "anchor": 3,
    }


def test_label_list_arrows(js):
    rows = [
        {"kind": "h", "id": "a"},
        {"kind": "a", "id": "n1"},
        {"kind": "h", "id": "b"},
    ]
    assert js(f"return edListMove({json.dumps(rows)}, null, 1);") == rows[0]
    assert js(f"return edListMove({json.dumps(rows)}, null, -1);") == rows[2]
    cur = rows[0]
    cur = js(f"return edListMove({json.dumps(rows)}, {json.dumps(cur)}, 1);")
    assert cur == rows[1]
    cur = js(f"return edListMove({json.dumps(rows)}, {json.dumps(cur)}, 1);")
    assert cur == rows[2]
    assert (
        js(f"return edListMove({json.dumps(rows)}, {json.dumps(cur)}, 1);") == rows[2]
    )
    assert (
        js(f"return edListMove({json.dumps(rows)}, {json.dumps(rows[0])}, -1);")
        == rows[0]
    )
    other = {"kind": "m", "id": "q1"}
    assert (
        js(f"return edListMove({json.dumps(rows)}, {json.dumps(other)}, 1);") == rows[0]
    )
    assert (
        js(f"return edListMove({json.dumps(rows)}, {json.dumps(other)}, -1);")
        == rows[2]
    )
    assert js("return edListMove([], null, 1);") is None


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


def test_selection_text(js):
    assert js("return selectionText({slug: 'case', docs: []});") == ""
    one = js(
        "return selectionText({slug: 'case', docs: [{uuid: 'u1', label: 'Ruling'}], labels: ['k1']});"
    )
    assert one == 'In evid set "case" I selected "Ruling" (u1). Labels: k1. '
    q = js(
        "return selectionText({slug: 'case', docs: [{uuid: 'u1', label: 'R'}], span: {page: 3, start: 10, end: 19, text: 'the words'}});"
    )
    assert 'Span on page 3, characters 10-19: "the words".' in q
    named = js(
        "return selectionText({slug: 'case', docs: [{uuid: 'u1', label: 'R'}], labelKey: 'the-words'});"
    )
    assert "Label: the-words." in named
    two = js(
        "return selectionText({slug: 'c', docs: [{uuid: 'a', label: 'A'}, {uuid: 'b', label: 'B'}]});"
    )
    assert 'the documents "A" (a), "B" (b)' in two


BASE = "# Notes\\n\\n- a\\n- b\\n\\n## Done\\n\\n- c\\n"


def test_merge3_from_treedit(js):
    # the same cases treedit tests: separate edits merge, an edit already on disk is not doubled,
    # near-duplicate edits of the same lines are a conflict
    assert js(
        f"const B = '{BASE}'; return merge3(B, B.replace('- a', '- a, mine'), B.replace('- c', '- c, theirs'));"
    ) == BASE.replace("\\n", "\n").replace("- a", "- a, mine").replace(
        "- c", "- c, theirs"
    )
    assert (
        js(f"const B = '{BASE}'; const m = B + '\\nNew.\\n'; return merge3(B, m, m);")
        == BASE.replace("\\n", "\n") + "\nNew.\n"
    )
    assert (
        js(f"const B = '{BASE}'; return merge3(B, B + '\\nteh\\n', B + '\\nthe\\n');")
        is None
    )


def test_merge_fields(js):
    out = js("""return mergeFields(
        {title: 'T', authors: 'A', notes: 'n'},
        {title: 'T', authors: 'A mine', notes: 'n mine'},
        {title: 'T disk', authors: 'A', notes: 'n disk'},
        ['title', 'authors', 'notes']);""")
    assert out == {
        "values": {"title": "T disk", "authors": "A mine", "notes": "n mine"},
        "conflicts": ["notes"],
    }
    same = js("return mergeFields({t: 'x'}, {t: 'y'}, {t: 'y'}, ['t']);")
    assert same == {"values": {"t": "y"}, "conflicts": []}


def test_freshness(js):
    assert js(
        "return [freshness(100, 100, 900), freshness(100, 550, 900), freshness(100, 2000, 900)];"
    ) == [1, 0.5, 0]


def test_history_chips(js):
    items = json.dumps(
        [
            {"kind": "details", "fields": ["title", "tags"]},
            {
                "kind": "labels",
                "file": "label/labels.json",
                "added": ["k1"],
                "removed": ["k0"],
            },
            {
                "kind": "pass",
                "id": "p1",
                "job": "dates",
                "model": "m",
                "matched": 2,
                "tried": 3,
            },
            {"kind": "notes", "paths": ["original.pdf"]},
            {"kind": "files", "what": "added", "files": ["scan.pdf"]},
        ]
    )
    chips = js(f"return historyChips({items}).map(c => c[1]);")
    assert chips == [
        "✎ title, tags",
        "+ k1",
        "− k0",  # noqa: RUF001 — the chip uses a real minus
        "pass: dates (2/3)",
        "🗨 note on original.pdf",
        "added scan.pdf",
    ]


def test_agent_badge(js):
    assert js(
        "return [agentBadge(['claude']), agentBadge(['claude', 'fish', 'codex']), agentBadge([]), agentBadge(undefined)];"
    ) == ["claude", "claude +2", "agent", "agent"]


def test_note_line_and_filter_by_note(js):
    assert js("return noteLine('one\\ntwo\\nthree');") == "one (+2)"
    assert js("return noteLine('  single  ');") == "single"
    docs = json.dumps(
        [
            {"uuid": "a", "label": "A", "tags": [], "note": "Signed by the board"},
            {"uuid": "b", "label": "B", "tags": []},
        ]
    )
    assert js(f"return filterDocs({docs}, 'board', new Set()).map(d => d.uuid);") == [
        "a"
    ]
