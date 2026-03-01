"""
LinkedIn Job Alert Agent
━━━━━━━━━━━━━━━━━━━━━━━━
• Fetches remote jobs + abroad (worldwide/global) jobs from LinkedIn
• Filters OUT jobs that restrict applicants to a specific country
• Sends Telegram alerts for every new matching job
• Designed to run as a one-shot script (via GitHub Actions cron)
"""

import os
import re
import json
import time
import logging
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION  — values are overridden by environment variables in CI
# ─────────────────────────────────────────────────────────────────────────────
CONFIG = {
    # Telegram (set as GitHub Secrets → env vars)
    "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE"),
    "TELEGRAM_CHAT_ID":   os.getenv("TELEGRAM_CHAT_ID",   "YOUR_CHAT_ID_HERE"),

    # Job roles to monitor (targeting senior/L2 positions for 6.5 years experience)
    "JOB_KEYWORDS": [
        "Senior SDET",
        "SDET",
        "Senior Automation Engineer",
        "Senior QA Automation",
        "Senior Test Automation Engineer",
        "Lead SDET",
    ],

    # Experience level (3=Mid-Senior level, 4=Director, for 6.5 years experience)
    "EXPERIENCE_LEVEL": "3",  # LinkedIn f_E=3 for Mid-Senior level

    # Abroad locations to search (these fetch jobs posted for worldwide audiences)
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

    # Max jobs per single Telegram message
    "MAX_JOBS_PER_MESSAGE": 5,

    # File to persist seen job IDs across runs (committed back to repo by CI)
    "SEEN_JOBS_FILE": "seen_jobs.json",
}

# ─────────────────────────────────────────────────────────────────────────────
#  PHRASES that indicate a job is restricted to locals of a specific country.
#  If ANY of these appear in the job description/title/location we skip it.
# ─────────────────────────────────────────────────────────────────────────────
RESTRICTED_PHRASES = [
    r"\blocal\s+candidates?\s+only\b",
    r"\bmust\s+(be|reside|live|located?)\s+(in|within)\b",
    r"\bonly\s+(candidates?|applicants?)\s+(from|in|based\s+in)\b",
    r"\b(citizen|citizenship|national)\s+required\b",
    r"\bwork\s+authorization\s+required\b",        # too vague for abroad
    r"\bno\s+visa\s+sponsorship\b",
    r"\bauthorized\s+to\s+work\s+in\b",
    r"\bpermanent\s+resident\b",
    r"\bresidence\s+permit\s+required\b",
    r"\bonly\s+in\s+(india|usa|uk|germany|australia|canada)\b",
]
RESTRICTED_RE = re.compile("|".join(RESTRICTED_PHRASES), re.IGNORECASE)

# LinkedIn f_WT values
REMOTE_CODE = "2"   # fully remote

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

LINKEDIN_SEARCH_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)
LINKEDIN_JOB_DETAIL_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ─────────────────────────────────────────────────────────────────────────────
#  SEEN-JOBS  (persisted in seen_jobs.json so GitHub Actions can commit it)
# ─────────────────────────────────────────────────────────────────────────────
def load_seen_jobs() -> set:
    path = CONFIG["SEEN_JOBS_FILE"]
    if os.path.exists(path):
        with open(path) as f:
            return set(json.load(f))
    return set()


def save_seen_jobs(seen: set):
    with open(CONFIG["SEEN_JOBS_FILE"], "w") as f:
        json.dump(sorted(seen), f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
#  LINKEDIN FETCHER
# ─────────────────────────────────────────────────────────────────────────────
def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)          # strip HTML tags
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&#\d+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_jobs_for_keyword_location(keyword: str, location: str, remote_only: bool) -> list[dict]:
    """Call LinkedIn guest API and parse returned HTML."""
    params: dict = {
        "keywords": keyword,
        "start":    0,
        "sortBy":   "DD",        # newest first
        "f_TPR":    "r86400",    # last 24 h — keeps results fresh
        "f_E":      CONFIG["EXPERIENCE_LEVEL"],  # Mid-Senior level
    }
    if remote_only:
        params["f_WT"] = REMOTE_CODE
    else:
        params["location"] = location

    try:
        resp = requests.get(
            LINKEDIN_SEARCH_URL, params=params, headers=HEADERS, timeout=15
        )
        if resp.status_code != 200:
            log.warning(f"HTTP {resp.status_code} for '{keyword}' / '{location}'")
            return []
        html = resp.text
    except Exception as e:
        log.error(f"Request failed for '{keyword}' / '{location}': {e}")
        return []

    job_ids   = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    titles    = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*(.*?)\s*</h3>', html, re.DOTALL)
    companies = re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>.*?<a[^>]*>\s*(.*?)\s*</a>', html, re.DOTALL)
    locations_raw = re.findall(r'<span[^>]*job-search-card__location[^>]*>(.*?)</span>', html, re.DOTALL)

    jobs = []
    for i, job_id in enumerate(job_ids):
        title    = _clean(titles[i])        if i < len(titles)        else "N/A"
        company  = _clean(companies[i])     if i < len(companies)     else "N/A"
        loc      = _clean(locations_raw[i]) if i < len(locations_raw) else location
        jobs.append({
            "id":       job_id,
            "title":    title,
            "company":  company,
            "location": loc,
            "url":      f"https://www.linkedin.com/jobs/view/{job_id}/",
            "keyword":  keyword,
            "remote":   remote_only,
        })
    log.info(f"  {len(jobs):2d} raw results  —  keyword='{keyword}'  location='{location or 'Remote'}'")
    return jobs


def fetch_job_description(job_id: str) -> str:
    """Fetch the detail page of a single job and return plain-text description."""
    try:
        resp = requests.get(
            LINKEDIN_JOB_DETAIL_URL.format(job_id=job_id),
            headers=HEADERS,
            timeout=12,
        )
        if resp.status_code == 200:
            return _clean(resp.text)
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────────────────────────
#  FILTERS
# ─────────────────────────────────────────────────────────────────────────────
def is_open_to_all(job: dict) -> bool:
    """
    Return True if the job appears open to international / remote applicants.
    Fetches the job detail page and checks for restriction phrases.
    Also rejects if the title itself signals a local-only posting.
    """
    # Quick title check
    if RESTRICTED_RE.search(job["title"]):
        log.info(f"    ✗ Skipping (title restricted): {job['title']}")
        return False

    # Fetch description and check
    description = fetch_job_description(job["id"])
    if RESTRICTED_RE.search(description):
        log.info(f"    ✗ Skipping (description restricted): {job['title']} @ {job['company']}")
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN FETCH PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
def fetch_all_qualifying_jobs(seen: set) -> list[dict]:
    """
    Two passes (parallelized for speed):
      1. Remote jobs (LinkedIn f_WT=2, no location bias)
      2. Abroad locations with worldwide audience
    Then deduplicate, filter already-seen, and check for restrictions.
    """
    raw: dict[str, dict] = {}   # job_id → job dict (dedup)

    # Build all search tasks
    search_tasks = []
    
    # Pass 1 — Pure remote (no location)
    log.info("━━━ Pass 1: Remote jobs (LinkedIn f_WT=2) ━━━")
    for keyword in CONFIG["JOB_KEYWORDS"]:
        search_tasks.append((keyword, "", True))

    # Pass 2 — Abroad locations (not restricted to local)
    log.info("━━━ Pass 2: Abroad / worldwide locations ━━━")
    for keyword in CONFIG["JOB_KEYWORDS"]:
        for location in CONFIG["ABROAD_LOCATIONS"]:
            search_tasks.append((keyword, location, False))

    # Execute all searches with controlled rate limiting to avoid HTTP 429
    log.info(f"Executing {len(search_tasks)} searches with rate limiting...")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        future_to_task = {}
        
        # Submit tasks with staggered delays to avoid overwhelming LinkedIn
        for i, (kw, loc, remote) in enumerate(search_tasks):
            future = executor.submit(fetch_jobs_for_keyword_location, kw, loc, remote)
            futures.append(future)
            future_to_task[future] = (kw, loc)
            # Stagger submissions: 0.4s delay between each task submission
            if i < len(search_tasks) - 1:
                time.sleep(0.4)
        
        for future in as_completed(futures):
            kw, loc = future_to_task[future]
            try:
                jobs = future.result()
                for job in jobs:
                    raw.setdefault(job["id"], job)
            except Exception as e:
                log.error(f"Search failed for '{kw}' / '{loc}': {e}")

    log.info(f"\nTotal unique raw jobs: {len(raw)}")

    # Filter already-seen
    new_jobs = [j for j in raw.values() if j["id"] not in seen]
    log.info(f"New (unseen) jobs    : {len(new_jobs)}")

    # Filter restricted postings with controlled rate limiting
    qualifying = []
    log.info("Checking job restrictions with rate limiting...")
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        future_to_job = {}
        
        # Submit detail check tasks with staggered delays
        for i, job in enumerate(new_jobs):
            future = executor.submit(is_open_to_all, job)
            futures.append(future)
            future_to_job[future] = job
            # Stagger submissions: 0.3s delay between each task
            if i < len(new_jobs) - 1:
                time.sleep(0.3)
        
        for future in as_completed(futures):
            job = future_to_job[future]
            try:
                if future.result():
                    qualifying.append(job)
                    log.info(f"    ✓ Qualifying: {job['title']} @ {job['company']} ({job['location']})")
            except Exception as e:
                log.error(f"Failed to check job {job['id']}: {e}")

    log.info(f"Qualifying jobs      : {len(qualifying)}")
    return qualifying


# ─────────────────────────────────────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────────────────────────────────────
def send_telegram(message: str) -> bool:
    token = CONFIG["TELEGRAM_BOT_TOKEN"]
    chat  = CONFIG["TELEGRAM_CHAT_ID"]
    url   = f"https://api.telegram.org/bot{token}/sendMessage"
    data  = {
        "chat_id":                  chat,
        "text":                     message,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code == 200:
            return True
        log.error(f"Telegram error {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")
    return False


def format_job_message(jobs: list[dict]) -> str:
    tag = lambda j: "🌐 Remote" if j.get("remote") else f"✈️ Abroad"
    header = (
        f"🚀 <b>LinkedIn Job Alert</b>\n"
        f"📅 {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}\n"
        f"🔍 <b>{len(jobs)}</b> new qualifying job(s)\n"
        f"{'─'*32}\n\n"
    )
    body = ""
    for j in jobs:
        body += (
            f"💼 <b>{j['title']}</b>\n"
            f"🏢 {j['company']}\n"
            f"📍 {j['location']}\n"
            f"🏷 {tag(j)} · {j['keyword']}\n"
            f"🔗 <a href='{j['url']}'>View Job</a>\n\n"
        )
    return header + body


def notify(jobs: list[dict]):
    """Split into batches and send each as a separate Telegram message."""
    batch_size = CONFIG["MAX_JOBS_PER_MESSAGE"]
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i : i + batch_size]
        msg   = format_job_message(batch)
        ok    = send_telegram(msg)
        log.info(f"Telegram batch {i//batch_size + 1} sent: {ok}")
        time.sleep(1)


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT  (one-shot — designed to be called by GitHub Actions cron)
# ─────────────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 58)
    log.info("  LinkedIn Job Alert Agent  —  one-shot run")
    log.info(f"  Roles    : {', '.join(CONFIG['JOB_KEYWORDS'])}")
    log.info(f"  Mode     : Remote + Open Abroad")
    log.info("=" * 58)

    seen = load_seen_jobs()
    qualifying = fetch_all_qualifying_jobs(seen)

    if qualifying:
        notify(qualifying)
        for j in qualifying:
            seen.add(j["id"])
        save_seen_jobs(seen)
        log.info(f"Done. {len(qualifying)} job(s) notified. seen_jobs.json updated.")
    else:
        log.info("No new qualifying jobs found. Nothing to notify.")
        # Send a daily heartbeat so you know the agent is alive
        send_telegram(
            f"ℹ️ <b>Daily Job Check Complete</b>\n"
            f"📅 {datetime.utcnow().strftime('%d %b %Y')}\n"
            f"No new remote/abroad jobs found today.\n"
            f"Agent is running fine ✅"
        )


if __name__ == "__main__":
    main()
