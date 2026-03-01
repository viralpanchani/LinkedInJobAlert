# 🤖 LinkedIn Job Alert Agent

[![Daily Job Alert](https://github.com/YOUR_USERNAME/linkedin-job-alert-agent/actions/workflows/daily_job_alert.yml/badge.svg)](https://github.com/YOUR_USERNAME/linkedin-job-alert-agent/actions/workflows/daily_job_alert.yml)

Automatically monitors LinkedIn for **Remote & Abroad** job postings for SDET, Automation Engineer, and related roles — and sends instant **Telegram alerts** every morning.

> ✅ **Smart Filtering**: Skips jobs that are restricted to candidates from a specific country (local-only roles). Only alerts you for jobs open to international applicants.

---

## 🌟 Features

| Feature | Detail |
|---------|--------|
| 🌐 **Remote jobs** | Fetches all remote-tagged LinkedIn jobs (f_WT=2) |
| ✈️ **Abroad jobs** | Searches worldwide, US, UK, EU, Canada, Australia, Singapore, etc. |
| 🚫 **Restriction filter** | Skips postings that say "local candidates only", "must reside in", "no visa sponsorship", etc. |
| 📱 **Telegram alerts** | Rich HTML messages with title, company, location, and direct link |
| 🧠 **No duplicates** | `seen_jobs.json` tracks notified jobs; committed back to repo after each run |
| ⏰ **Daily cron** | GitHub Actions runs every day at 8:00 AM IST (02:30 UTC) |
| 💰 **Zero cost** | GitHub Actions free tier is sufficient |

---

## 📱 Sample Telegram Alert

```
🚀 LinkedIn Job Alert
📅 01 Mar 2026, 02:31 UTC
🔍 4 new qualifying job(s)
────────────────────────────────

💼 Senior SDET
🏢 Stripe
📍 Remote
🏷 🌐 Remote · SDET
🔗 View Job

💼 Automation Engineer
🏢 Booking.com
📍 Amsterdam, Netherlands
🏷 ✈️ Abroad · Automation Engineer
🔗 View Job
```

---

## 🛠️ Setup (5 Steps)

### Step 1 — Fork / Clone this repo

```bash
git clone https://github.com/YOUR_USERNAME/linkedin-job-alert-agent.git
cd linkedin-job-alert-agent
```

### Step 2 — Create a Telegram Bot

1. Open Telegram → message **@BotFather**
2. `/newbot` → follow prompts → copy the **Bot Token**
3. Start a chat with your new bot
4. Visit this URL in a browser (replace `<TOKEN>`):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
5. Send any message to your bot, refresh the URL → find `"chat":{"id": XXXXXX}` → that's your **Chat ID**

### Step 3 — Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value |
|-------------|-------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your chat/group ID |

### Step 4 — Enable GitHub Actions

Go to **Actions** tab in your repo → click **"I understand my workflows, go ahead and enable them"** if prompted.

### Step 5 — Test manually

Go to **Actions → LinkedIn Job Alert — Daily Run → Run workflow** to trigger it immediately and verify Telegram messages arrive.

---

## ⚙️ Customising

Open `linkedin_job_alert.py` and edit the `CONFIG` block:

```python
CONFIG = {
    # Add/remove job roles
    "JOB_KEYWORDS": [
        "SDET",
        "Automation Engineer",
        "QA Automation",
        "Test Automation Engineer",
        "Software Development Engineer in Test",
        "Test Engineer",
    ],

    # Add/remove target abroad countries/regions
    "ABROAD_LOCATIONS": [
        "Worldwide",
        "Europe",
        "United States",
        "United Kingdom",
        "Canada",
        "Germany",
        "Netherlands",
        "Australia",
        "Singapore",
    ],

    # Max jobs per single Telegram message (to avoid flooding)
    "MAX_JOBS_PER_MESSAGE": 5,
}
```

### Change the schedule

Edit `.github/workflows/daily_job_alert.yml`:

```yaml
on:
  schedule:
    # Format: minute hour day month weekday (UTC)
    - cron: "30 2 * * *"   # 02:30 UTC = 08:00 AM IST
    # - cron: "0 9 * * 1-5" # 9:00 AM UTC, weekdays only
```

---

## 🔍 How the Restriction Filter Works

When a new job is found, the agent fetches its full detail page and scans the description for phrases like:

- `local candidates only`
- `must reside in / must be located in`
- `only candidates from / only applicants in`
- `no visa sponsorship`
- `authorized to work in`
- `citizenship required`
- `permanent resident`

If **any** of these are found → job is **skipped**. Only truly open-to-all postings get through.

---

## 📂 Repo Structure

```
linkedin-job-alert-agent/
├── linkedin_job_alert.py          # Main agent script
├── seen_jobs.json                 # Auto-updated by CI (tracks notified jobs)
├── requirements.txt
├── .gitignore
├── .github/
│   └── workflows/
│       └── daily_job_alert.yml    # GitHub Actions cron workflow
└── README.md
```

---

## 🚀 Running Locally

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

python linkedin_job_alert.py
```

---

## ⚠️ Notes

- LinkedIn's public API has no official rate limit documentation — the agent uses conservative delays (1–2s) between requests to be polite.
- `seen_jobs.json` is committed back to the repo after each run so the next run doesn't re-notify old jobs.
- The `[skip ci]` commit message on `seen_jobs.json` updates prevents infinite workflow loops.
