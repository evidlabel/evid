from evid.cli.main import app


def test_gui_help_says_minus_d_opens_the_data_dir():
    gui = next(c for c in app.commands if c.name == "gui")
    text = f"{gui.help} " + " ".join(a.help or "" for a in (gui.arguments or []))
    lowered = text.lower()
    assert "-d" in lowered or "--db" in lowered
    assert "data dir" in lowered or "data directory" in lowered
    assert "chdir" in lowered or "working directory" in lowered
