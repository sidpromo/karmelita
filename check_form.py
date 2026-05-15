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
        print(f"  {name}={value}")


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
        phrase.lower() in html.lower() for phrase in UNAVAILABLE_PHRASES
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
        print("\nBaseline created. No alert on first run.")
    elif changed:
        print(f"\nCHANGE DETECTED: {previous_key} -> {monitor_key}")
    else:
        print("\nNo form change detected.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
