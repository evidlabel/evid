# Evidence Manager — Demographic Inversion in Fake Identity Generation

Addendum to evidence_manager_workflows.md §2 (Anon Output Mode).

---

## Motivation

In social law (personal injury, child custody, disability assessment, benefits disputes),
LLMs may reproduce biases from training data. A case involving "Lars Hansen" (Danish
male name) may receive subtly different analysis than the same case with a name
perceived as female, immigrant, or from a specific ethnic background.

The fake identity feature allows a practitioner to systematically invert one or more
demographic dimensions of a client identity before sending the case to an LLM. Running
the same prompt with demographic variants is a methodological check: if the legal
analysis changes, the LLM is not operating on facts alone.

---

## 1. Fake Profile Concept

A **fake profile** is a named configuration attached to an anonymous set that controls
how entity replacements are generated. Multiple profiles can coexist per set, letting
the user generate three or four demographic variants of the same case and compare
LLM outputs side by side.

### Dimensions controlled per profile

| Dimension | Options |
|---|---|
| Gender | same · inverted · male · female · neutral |
| Ethnicity / name origin | same · inverted · danish · arabic · somali · turkish · eastern-european · ... |
| Age | same · inverted (young↔old) · fixed range |
| CPR / ID numbers | re-generated to match fake demographics |

"Inverted" is always relative to the detected attribute of the original entity.
"Same" preserves the perceived demographic but generates a different individual.

---

## 2. Updated Entity YAML Schema

```yaml
detected:
  gender: male              # detected by name gender classifier
  name_origin: danish       # detected by name origin classifier
  age_estimate: 42          # extracted from DOB/CPR if present, else null

profiles:
  same:
    name: "Erik Madsen"
    placeholder: "[PERSON A]"

  gender_inverted:
    name: "Rikke Madsen"
    placeholder: "[PERSON A]"

  ethnicity_inverted:
    name: "Karim Al-Amin"
    placeholder: "[PERSON A]"

  both_inverted:
    name: "Fatima Al-Rashidi"
    placeholder: "[PERSON A]"
```

For non-person entities (addresses, CPR numbers), profiles generate consistent
replacements that match the active person profile — the CPR is re-generated with
the correct gender digit (4th digit: odd = male, even = female in Danish CPR format).

---

## 3. Detection

Detection runs as part of `AnonService.run_extract()` for PERSON entities.

### Gender detection
Use `gender-guesser` (PyPI) or `nameparser` + a lookup table of common Danish
first names by gender. Confidence threshold: if below 0.7, mark as `unknown` and
default to neutral in all profiles.

### Name origin detection
Use `ethnicolr` (PyPI, trained on Wikipedia/voter roll data) or a simpler lookup
against Statistics Denmark's published name frequency tables by origin category.
The app ships with a bundled lookup table for Danish, Arabic, Somali, Turkish, and
Eastern European origins — no network call required.

Categories are intentionally coarse — this is not about precision, it is about
generating a name that an LLM will perceive as belonging to a different demographic
group.

### Age / gender from CPR
Danish CPR numbers encode date of birth and gender (last digit odd = male, even =
female). `did extract` already detects CPR numbers; extend the extractor to decode
DOB and gender from the CPR and store in `detected`.

---

## 4. Fake Name Generation

Fake names are generated from locale-aware name pools, not from `faker` alone
(which has insufficient coverage of non-Western Danish names). The app ships with
bundled name lists:

```
data/names/
  danish_male_first.txt       # top 500 Danish male first names (DST)
  danish_female_first.txt
  danish_last.txt
  arabic_male_first.txt       # common Arabic names present in Danish population
  arabic_female_first.txt
  arabic_last.txt
  somali_male_first.txt
  somali_female_first.txt
  somali_last.txt
  turkish_male_first.txt
  turkish_female_first.txt
  turkish_last.txt
  eastern_european_male_first.txt
  eastern_european_female_first.txt
  eastern_european_last.txt
```

Name selection uses a seeded random draw keyed on `(doc_uuid, entity_index,
profile_name)` so that:
1. The same entity always gets the same fake name within a profile.
2. Different entities get different names.
3. Different profiles for the same entity get names consistent with that profile's
   demographics.

```python
def generate_fake_name(
    entity_idx: int,
    doc_uuid: str,
    target_gender: str,       # 'male' | 'female' | 'neutral'
    target_origin: str,       # 'danish' | 'arabic' | 'somali' | ...
    profile_name: str,
) -> str:
    seed = hash((doc_uuid, entity_idx, profile_name)) & 0xFFFFFFFF
    rng = random.Random(seed)
    first = rng.choice(name_pool(target_origin, target_gender, 'first'))
    last  = rng.choice(name_pool(target_origin, target_gender, 'last'))
    return f"{first} {last}"
```

---

## 5. Profile Management UI

### In the Anonymize panel — new "Fake profiles" section

```
Fake profiles
─────────────────────────────────────────────────────
  same               Erik Madsen, Bredgade 88, ...  [set active]  [delete]
  gender_inverted    Rikke Madsen, Bredgade 88, ...  [set active]  [delete]
  ethnicity_inverted Karim Al-Amin, Enghave Plads 4, ... [set active] [delete]
  both_inverted      Fatima Al-Rashidi, ...          ★ active      [delete]
─────────────────────────────────────────────────────
  [+ Generate profiles...]
```

"Generate profiles..." opens a dialog:

```
Generate fake profiles

  Dimensions to vary:
    [x] Gender inversion
    [x] Ethnicity inversion
    [ ] Age inversion

  Target origin for inversion:
    ( ) Arabic   (•) Somali   ( ) Turkish   ( ) Eastern European

  [Generate]   → creates 4 profiles: same, gender_inverted, ethnicity_inverted, both_inverted
```

The active profile determines which `fake` values are used when the anon mode is set
to Fake. Switching the active profile is instant — no reprocessing.

---

## 6. Anon Mode Updated

The 3-state toggle becomes: **Real · Placeholder · Fake**

When mode is Fake, the active fake profile's values are substituted. The profile name
is shown next to the mode badge in the prompt preview:

```
mode: fake (gender_inverted)
```

---

## 7. Bias Testing Workflow

The intended usage pattern:

1. Build a prompt by tag (`hansen.psych`) in the Prompt Builder.
2. Export 4 times — once per profile — saving each to a file:
   - `prompt_same.txt`
   - `prompt_gender_inverted.txt`
   - `prompt_ethnicity_inverted.txt`
   - `prompt_both_inverted.txt`
3. Submit all four to the LLM (or a comparison tool).
4. Diff the outputs. Any substantive difference in legal analysis or recommendation
   is attributable only to the demographic presentation, since all other facts are
   identical.

### Batch export action

Add a `[Batch export all profiles]` button to the prompt builder export controls.
This produces all profiles' outputs in a single operation, named with the profile
suffix. Each file includes a header comment:

```
# Fake profile: gender_inverted
# Generated: 2024-11-06T11:30:00
# Active YAML: 2024-11-05T09:10:00_entities.yml
# Set: Hansen Case 2024
# Tags: hansen.psych
```

This header makes the files self-documenting for later comparison.

---

## 8. Legal / Ethical Note (for app documentation)

The demographic inversion feature is a **methodological tool for detecting LLM bias**,
not a tool for misrepresenting a client. The original case documents are always
preserved unmodified. Fake profiles are only ever used in the LLM prompt — never in
any court filing, report, or client-facing document.

App documentation should make clear:
- Which output mode is active at export time (shown in the file header).
- That all fake outputs are derived from a reversible mapping stored in the YAML.
- That the tool makes no claim about whether a particular LLM is or is not biased —
  comparison of outputs is left to the practitioner's judgment.
