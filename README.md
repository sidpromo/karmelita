# Karmelita Form Monitor

Monitors `https://szabadkarmelita.hu/` for new Jotform booking forms. When the form ID changes, sends a push notification via [ntfy](https://ntfy.sh) and creates a GitHub issue.

## What it does

- Fetches the entry URL hourly, follows redirects
- Extracts the Jotform form ID from the final URL or page HTML
- Compares against the previously stored state
- If the form changes: creates a GitHub issue + sends an ntfy push notification

## What it does NOT do

- Book appointments
- Detect individual time slots
- Bypass CAPTCHA or bot protection
- Auto-submit anything

## State file

The monitor stores its state in `.state/karmelita-form.json`. This file is committed to the repo by the workflow so state persists across runs. On first run, a baseline is created without triggering alerts.

## Run locally

```bash
uv sync
uv run python check_form.py
```

## Trigger manually

Go to Actions → "Check Karmelita form" → "Run workflow" in the GitHub UI.

## Notifications

**Push notifications (ntfy):** Subscribe to the topic `karmelita-hagymasbab` in the [ntfy app](https://ntfy.sh) (Android/iOS). Everyone subscribed gets instant push notifications when the form changes.

**GitHub Issues:** A new issue is created in the repo on each detected change. If you're watching the repo, GitHub sends you an email too.

## Setup

Add this repository secret (Settings → Secrets and variables → Actions → New repository secret):

| Secret | Value |
|--------|-------|
| `NTFY_TOPIC` | your ntfy topic name |

## Future improvements

- Milestone 2: detect whether appointment slots are actually selectable (requires Playwright)
- More frequent polling when a form change is first detected
- Telegram/Discord notification options
