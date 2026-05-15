# Karmelita Jotform Availability Monitor — Kiro Implementation Spec

## Goal

Create a small GitHub Actions based monitor that detects when `https://szabadkarmelita.hu/` starts pointing to a new Jotform booking form.

The first milestone is **not** to book anything and **not** to detect individual appointment slots.  
The first milestone is only:

> Detect when the stable public entry URL redirects to a new Jotform form URL / form ID, then notify me.

## Context

The public booking flow appears to use:

```text
https://szabadkarmelita.hu/
        ↓ redirects or links to
https://form.jotform.com/<FORM_ID>/
```

Old/known Jotform URLs may become unavailable, so monitoring a fixed Jotform URL is not reliable.

The stable URL to monitor is:

```text
https://szabadkarmelita.hu/
```

When a new booking period opens, the site may redirect to a new Jotform form ID.  
Therefore the monitor should track the effective final URL and extract the Jotform form ID.

## Requirements

### Functional requirements

1. Run on a schedule using GitHub Actions.
2. Monitor this entry URL:

   ```text
   https://szabadkarmelita.hu/
   ```

3. Follow redirects.
4. Detect the final URL after redirects.
5. If the final URL is a Jotform URL, extract the numeric Jotform form ID.
6. If the final URL is not directly Jotform, inspect the returned HTML and try to find a Jotform URL inside it.
7. Store the last known monitor state in the repository.
8. On first run, create a baseline state and do **not** alert.
9. On later runs, compare the previous detected monitor key with the current one.
10. If the monitor key changes, create a GitHub issue as notification.
11. Commit the updated state file after every detected state change.

### Non-functional requirements

1. Keep the solution simple.
2. Use Python.
3. Use `requests` first; do not use Playwright in milestone 1 unless needed.
4. Use `uv` for dependency management and virtual environments (no pip/venv).
5. Poll politely. An hourly schedule is enough for the first version.
6. Do not attempt to bypass CAPTCHA, login, rate limits, anti-bot checks, hidden APIs, or any access restrictions.
7. The script must be safe to run repeatedly.
8. Handle network failures gracefully: if the target site is unreachable or returns an error, log the failure and exit cleanly without updating state or triggering alerts.
9. The GitHub Action must support manual triggering with `workflow_dispatch`.
10. The code should be readable and easy to extend later.

## Repository structure

The repository is named `karmelita` (renamed from any previous name if needed). All files live at the repository root:

```text
karmelita/              ← repo root
├── .github/
│   └── workflows/
│       └── check-karmelita.yml
├── .gitignore
├── .state/
│   └── .gitkeep
├── pyproject.toml
├── check_form.py
└── README.md
```

The `.gitignore` should exclude:

```text
.venv/
__pycache__/
*.pyc
```

## Monitor behavior

The Python script should produce a state object similar to:

```json
{
  "checked_at_utc": "2026-05-15T12:00:00+00:00",
  "entry_url": "https://szabadkarmelita.hu/",
  "final_url": "https://form.jotform.com/123456789012345",
  "jotform_url": "https://form.jotform.com/123456789012345",
  "form_id": "123456789012345",
  "monitor_key": "jotform:123456789012345",
  "unavailable": false,
  "content_hash": "..."
}
```

The most important field is:

```text
monitor_key
```

Use this logic:

```text
if Jotform form ID was found:
    monitor_key = "jotform:<FORM_ID>"
else:
    monitor_key = "final-url:<FINAL_URL>"
```

This makes the script robust even if the website temporarily stops redirecting directly to Jotform.

## Python implementation

Create `check_form.py`.

Expected responsibilities:

1. Fetch `https://szabadkarmelita.hu/`.
2. Follow redirects.
3. Extract final URL.
4. Extract Jotform URL.
5. Extract Jotform form ID.
6. Detect whether the form appears unavailable.
7. Load previous state from `.state/karmelita-form.json` if present.
8. Save current state to `.state/karmelita-form.json`.
9. Set GitHub Actions outputs:
   - `first_run`
   - `changed`
   - `monitor_key`
   - `previous_key`
   - `final_url`
   - `jotform_url`
   - `form_id`
   - `unavailable`
10. Print useful diagnostic output.

Suggested implementation:

```python
#!/usr/bin/env python3

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys

import requests

ENTRY_URL = "https://szabadkarmelita.hu/"
STATE_PATH = pathlib.Path(".state/karmelita-form.json")

UNAVAILABLE_PHRASES = [
    "Ez az űrlap jelenleg nem elérhető",
    "This form is currently not available",
    "form is currently not available",
]

JOTFORM_RE = re.compile(
    r"https?://(?:www\.)?(?:form|eu)\.jotform\.com/(\d+)[^\s\"'<>]*",
    re.IGNORECASE,
)

FORM_ID_RE = re.compile(
    r"(?:form|eu)\.jotform\.com/(\d+)",
    re.IGNORECASE,
)


def set_github_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def fetch_page() -> tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 karmelita-availability-monitor/1.0 "
            "(polite scheduled checker)"
        )
    }

    response = requests.get(
        ENTRY_URL,
        headers=headers,
        allow_redirects=True,
        timeout=30,
    )
    response.raise_for_status()

    return response.url, response.text


def extract_jotform_url(final_url: str, html: str) -> str | None:
    if "jotform.com" in final_url.lower():
        return final_url

    match = JOTFORM_RE.search(html)
    if match:
        return match.group(0)

    return None


def extract_form_id(url: str | None) -> str | None:
    if not url:
        return None

    match = FORM_ID_RE.search(url)
    return match.group(1) if match else None


def main() -> int:
    now = dt.datetime.now(dt.UTC).isoformat()

    try:
        final_url, html = fetch_page()
    except requests.RequestException as e:
        print(f"Network error: {e}")
        print("Exiting without updating state.")
        return 1

    jotform_url = extract_jotform_url(final_url, html)
    form_id = extract_form_id(jotform_url)

    unavailable = any(
        phrase.lower() in html.lower()
        for phrase in UNAVAILABLE_PHRASES
    )

    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()

    if form_id:
        monitor_key = f"jotform:{form_id}"
    else:
        monitor_key = f"final-url:{final_url}"

    current_state = {
        "checked_at_utc": now,
        "entry_url": ENTRY_URL,
        "final_url": final_url,
        "jotform_url": jotform_url,
        "form_id": form_id,
        "monitor_key": monitor_key,
        "unavailable": unavailable,
        "content_hash": content_hash,
    }

    previous_state = None
    if STATE_PATH.exists():
        previous_state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    first_run = previous_state is None
    previous_key = previous_state.get("monitor_key") if previous_state else None
    changed = (not first_run) and (previous_key != monitor_key)

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(current_state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    set_github_output("first_run", str(first_run).lower())
    set_github_output("changed", str(changed).lower())
    set_github_output("monitor_key", monitor_key)
    set_github_output("previous_key", previous_key or "")
    set_github_output("final_url", final_url)
    set_github_output("jotform_url", jotform_url or "")
    set_github_output("form_id", form_id or "")
    set_github_output("unavailable", str(unavailable).lower())

    print(json.dumps(current_state, indent=2, ensure_ascii=False))

    if first_run:
        print("Baseline created. No alert on first run.")
    elif changed:
        print(f"CHANGE DETECTED: {previous_key} -> {monitor_key}")
    else:
        print("No form change detected.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## GitHub Actions workflow

Create:

```text
.github/workflows/check-karmelita.yml
```

Suggested workflow:

```yaml
name: Check Karmelita form

on:
  schedule:
    - cron: "0 * * * *"
  workflow_dispatch:

permissions:
  contents: write
  issues: write

concurrency:
  group: karmelita-form-monitor
  cancel-in-progress: true

jobs:
  check:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install dependencies
        run: uv sync

      - name: Check form redirect
        id: check
        run: uv run python check_form.py

      - name: Commit updated state
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add .state/karmelita-form.json

          if git diff --cached --quiet; then
            echo "No state change to commit."
          else
            git commit -m "Update Karmelita form monitor state"
            git push
          fi

      - name: Create issue if form changed
        if: steps.check.outputs.changed == 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          REPO: ${{ github.repository }}
          PREVIOUS_KEY: ${{ steps.check.outputs.previous_key }}
          MONITOR_KEY: ${{ steps.check.outputs.monitor_key }}
          FINAL_URL: ${{ steps.check.outputs.final_url }}
          JOTFORM_URL: ${{ steps.check.outputs.jotform_url }}
          FORM_ID: ${{ steps.check.outputs.form_id }}
          UNAVAILABLE: ${{ steps.check.outputs.unavailable }}
        run: |
          cat > issue_body.md <<EOF
          A possible new Karmelita booking form was detected.

          Previous key: \`${PREVIOUS_KEY}\`
          Current key: \`${MONITOR_KEY}\`

          Final URL:
          ${FINAL_URL}

          Jotform URL:
          ${JOTFORM_URL}

          Form ID:
          ${FORM_ID}

          Form unavailable text detected:
          ${UNAVAILABLE}

          Next step: open the final URL manually and check whether appointment slots are selectable.
          EOF

          python - <<'PY'
          import json
          import pathlib
          import os

          body = pathlib.Path("issue_body.md").read_text(encoding="utf-8")

          payload = {
              "title": f"Karmelita form changed: {os.environ.get('FORM_ID') or os.environ.get('MONITOR_KEY')}",
              "body": body,
          }

          pathlib.Path("issue_payload.json").write_text(
              json.dumps(payload, ensure_ascii=False),
              encoding="utf-8",
          )
          PY

          curl --fail \
            --request POST \
            --url "https://api.github.com/repos/${REPO}/issues" \
            --header "Authorization: Bearer ${GH_TOKEN}" \
            --header "Accept: application/vnd.github+json" \
            --header "Content-Type: application/json" \
            --data @issue_payload.json

      - name: Push notification via ntfy
        if: steps.check.outputs.changed == 'true'
        env:
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
        run: |
          curl -s \
            -H "Title: Karmelita form changed" \
            -H "Priority: high" \
            -H "Tags: calendar,warning" \
            -d "New form detected: ${{ steps.check.outputs.monitor_key }}. Check: ${{ steps.check.outputs.final_url }}" \
            "https://ntfy.sh/${NTFY_TOPIC}"
```

## README requirements

Create `README.md` with:

1. What the project does.
2. What it does not do.
3. How the state file works.
4. How to run locally.
5. How to trigger the workflow manually.
6. How notifications work.
7. Future improvements.

Suggested local run instructions:

```bash
uv sync
uv run python check_form.py
```

## Acceptance criteria

The task is complete when:

1. The repository contains the expected files.
2. `python check_form.py` runs locally without syntax errors.
3. First run creates `.state/karmelita-form.json`.
4. First run does not mark `changed=true`.
5. Later runs compare the stored `monitor_key` against the current `monitor_key`.
6. If the monitor key changes, the workflow creates a GitHub issue.
7. The workflow commits the updated state file.
8. The workflow can be started manually from the GitHub Actions UI.
9. The scheduled workflow runs every hour.
10. The README explains the intended behavior clearly.

## Testing ideas

Add basic unit tests if time allows, especially for:

1. Extracting form ID from direct Jotform URL.
2. Extracting form ID from HTML containing a Jotform link.
3. Falling back to `final-url:<URL>` when no Jotform URL exists.
4. First-run behavior.
5. Changed/not-changed behavior.

Possible test cases:

```python
def test_extract_form_id_from_form_jotform_url():
    assert extract_form_id("https://form.jotform.com/261334114563046/") == "261334114563046"


def test_extract_form_id_from_eu_jotform_url():
    assert extract_form_id("https://eu.jotform.com/261334114563046/") == "261334114563046"


def test_extract_form_id_none():
    assert extract_form_id("https://szabadkarmelita.hu/") is None
```

## Future milestone: detect appointment availability

After the form-ID monitor works, add milestone 2:

> Open the currently detected Jotform page and detect whether appointment slots are selectable.

This may require Playwright because Jotform forms can render content dynamically with JavaScript.

Possible future behavior:

```text
GitHub Actions schedule
        ↓
Open szabadkarmelita.hu
        ↓
Resolve current Jotform URL
        ↓
Open rendered Jotform page with Playwright
        ↓
Look for unavailable text / selectable date fields / appointment options
        ↓
Create GitHub issue if availability is detected
```

Do not implement this in milestone 1 unless the simple redirect monitor is already working.

## Important safety / ethics note

This monitor should only check publicly available pages at a polite interval.  
It must not attempt to bypass CAPTCHA, login, bot protection, hidden restrictions, rate limits, or access controls.  
It must not auto-submit the form or book appointments.

