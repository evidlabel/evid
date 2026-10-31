"""The Agent pane's harness list: what a click in the pane can start."""

from __future__ import annotations

from evid.web.harnesses import agent_name, available, harnesses, opencode_profiles


def _which(*names):
    found = set(names)
    return lambda cmd: f"/usr/bin/{cmd}" if cmd in found else None


def test_command_name():
    assert agent_name("hermes --skills evid") == "hermes"
    assert agent_name("/usr/bin/fish") == "fish"
    assert agent_name("env X=1 codex") == "codex"
    assert agent_name("") == "shell"


def test_available_needs_the_first_word():
    assert available("claude --flag", _which("claude")) is True
    assert available("claude --flag", _which()) is False
    assert available("", _which("claude")) is False


def test_configured_agent_is_the_default_and_first():
    hs = harnesses("hermes --skills evid", which=_which("claude", "hermes"))
    assert hs[0]["label"] == "Hermes"
    assert hs[0]["command"] == "hermes --skills evid"
    assert hs[0]["default"] is True
    assert hs[0]["installed"] is True
    assert [h["id"] for h in hs].count("hermes") == 1


def test_first_installed_is_the_default_without_a_configured_agent():
    hs = harnesses(which=_which("codex"))
    assert hs[0]["id"] == "codex" and hs[0]["default"] is True
    assert [h["id"] for h in hs if h.get("default")] == ["codex"]
    assert {h["id"] for h in hs} >= {"claude", "codex", "hermes", "opencode"}
    assert next(h for h in hs if h["id"] == "claude")["installed"] is False


def test_unknown_configured_command_gets_its_own_row():
    hs = harnesses("myagent --fast", which=_which())
    assert hs[0]["id"] == "configured"
    assert hs[0]["label"] == "myagent"
    assert hs[0]["default"] is True


def test_opencode_profiles_follow_the_opencode_row(tmp_path):
    folder = tmp_path / "profiles"
    folder.mkdir()
    for name in ("local-qw38", "ds41-flash"):
        (folder / f"{name}.json").write_text("{}", "utf-8")
    (folder / "active").write_text("ds41-flash\n", "utf-8")
    assert opencode_profiles(folder) == [
        {"name": "ds41-flash", "active": True},
        {"name": "local-qw38", "active": False},
    ]
    hs = harnesses(profiles_dir=folder, which=_which("opencode", "ocprofile"))
    labels = [h["label"] for h in hs]
    assert "OpenCode · ds41-flash (active)" in labels
    assert labels.index("OpenCode") < labels.index("OpenCode · ds41-flash (active)")
    assert [h["command"] for h in hs if h["kind"] == "profile"] == [
        "ocprofile launch ds41-flash",
        "ocprofile launch local-qw38",
    ]


def test_a_configured_profile_is_that_profile(tmp_path):
    folder = tmp_path / "profiles"
    folder.mkdir()
    for name in ("local-qw38", "ds41-flash"):
        (folder / f"{name}.json").write_text("{}", "utf-8")
    hs = harnesses(
        "ocprofile launch local-qw38",
        profiles_dir=folder,
        which=_which("opencode", "ocprofile"),
    )
    assert hs[0]["command"] == "ocprofile launch local-qw38"
    assert hs[0]["label"] == "OpenCode · local-qw38"
    assert hs[0]["default"] is True
    assert [h["command"] for h in hs].count("ocprofile launch local-qw38") == 1


def test_no_profiles_without_ocprofile(tmp_path):
    (tmp_path / "x.json").write_text("{}", "utf-8")
    hs = harnesses(profiles_dir=tmp_path, which=_which("opencode"))
    assert [h["kind"] for h in hs if h["kind"] == "profile"] == []
    hs = harnesses(profiles_dir=tmp_path, which=_which("ocprofile"))
    assert [h["kind"] for h in hs if h["kind"] == "profile"] == []
