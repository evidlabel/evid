# evid × other evidskills

- **hudoc**: Primary source of fresh documents. Default output is per-doc `<uuid>/label.typ` + `info.yml` under `-o dir` — import into the evid set, then `doc label` / `set gather`. `-p` writes `{subsite}_doc_*.txt` for **precise-quoter** (`docs/<slug>.txt` after `source_slug.py`). Use plain text when running `did batch` first.
- **labquote**: Primary consumer of `set gather` Hayagriva YAML; do not hand-edit gathered entries.
- **notat**: Subset cited keys from the gather dump; see the `notat` skill.
- **lawcite**: Statute pathway; combine with evid only when mixing provision keys and labelled snippets in one Typst doc.
- **precise-quoter**: Complementary for sources you do not fully ingest in evid. Can share a `references.yml` Hayagriva file. Limitation: did-anon tokens in bib entries do not substitute on Typst compile today.
- **did-anon**: Run on sensitive collections **before** `evid doc add` if PII must never reach the model or stored set.
- **orgchart**: Membership pages alongside the evid set.
- **output-table**: After `doc add`, `set gather`, or any step that writes files — emit the output table last.
- **project-setup** + `notes/`: Version exports and case notes under the notes git repo.
