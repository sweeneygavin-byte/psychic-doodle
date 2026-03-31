"""
Gavin's Job Scanner v2
-----------------------
Uses Google search queries to find matching roles at target firms and job boards.
Much more reliable than scraping JavaScript-heavy careers pages directly.

Sends an email digest of new roles each weekday morning.
Setup: see README_SCANNER.md
"""

import os
import re
import json
import time
import hashlib
import smtplib
import datetime
import urllib.request
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── CONFIG ────────────────────────────────────────────────────────────────────

ROLE_QUERIES = [
    'COO OR "Chief Operating Officer"',
    '"Head of Trading" OR "Chief Trading Officer"',
    '"Head of Electronic Trading" OR "Head of Systematic Execution"',
    '"Head of Strategy" OR "Chief Strategy Officer"',
    '"MD Strategy" OR "Managing Director Strategy" OR "Strategy Business Development"',
    '"MD Market Structure" OR "Head of Market Structure"',
    '"Head of Markets" OR "Global Markets COO"',
]

SENIORITY = [
    "managing director", "md,", " md ", "chief", "head of",
    "director", "vice president", " vp ", "vp,", "partner", "president",
]

EXCLUDE = [
    "analyst", "associate", "intern", "graduate", "junior",
    "assistant", "coordinator", "entry level", "entry-level",
]

TARGET_FIRMS = [
    "Two Sigma", "D.E. Shaw", "Renaissance Technologies", "AQR Capital",
    "WorldQuant", "Citadel", "Point72", "Millennium Management",
    "Balyasny Asset Management", "ExodusPoint Capital", "Marshall Wace",
    "Capula Investment Management", "Vanguard", "Fidelity Investments",
    "State Street Global Advisors", "Wellington Management", "Nuveen TIAA",
    "JPMorgan", "Goldman Sachs", "Morgan Stanley", "Bank of America",
    "Barclays", "Citigroup", "UBS", "Wells Fargo", "MarketAxess",
    "Tradeweb", "Virtu Financial", "Bloomberg", "ION Group",
]

JOB_BOARD_SEARCHES = [
    {
        "name": "eFinancialCareers",
        "query": 'site:efinancialcareers.com (COO OR "head of trading" OR "head of strategy" OR "market structure") "New York" "director" OR "managing director" OR "chief"',
        "base_url": "efinancialcareers.com",
    },
    {
        "name": "Indeed",
        "query": 'site:indeed.com ("chief operating officer" OR "head of trading" OR "head of strategy") finance "New York"',
        "base_url": "indeed.com",
    },
    {
        "name": "Glassdoor",
        "query": 'site:glassdoor.com (COO OR "head of trading" OR "head of strategy") finance "New York" "managing director" OR "director"',
        "base_url": "glassdoor.com",
    },
]

SEEN_ROLES_FILE = "seen_roles.json"
EMAIL_FROM      = os.environ.get("EMAIL_FROM", "")
EMAIL_TO        = os.environ.get("EMAIL_TO", "sweeney_gavin@hotmail.com")
EMAIL_PASSWORD  = os.environ.get("EMAIL_PASSWORD", "")
SMTP_HOST       = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.environ.get("SMTP_PORT", "587"))


# ── HELPERS ───────────────────────────────────────────────────────────────────

def role_id(firm: str, title: str) -> str:
    return hashlib.md5(f"{firm.lower()}::{title.lower().strip()}".encode()).hexdigest()


def load_seen() -> set:
    if os.path.exists(SEEN_ROLES_FILE):
        with open(SEEN_ROLES_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_ROLES_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def fetch_url(url: str, timeout: int = 20) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")
    except Exception as e:
        print(f"    Fetch failed {url[:60]}: {e}")
        return ""


def google_search(query: str) -> list:
    """Search Google and parse result titles, URLs and snippets from HTML."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.google.com/search?q={encoded}&num=20&hl=en&gl=us"
    html = fetch_url(url)
    if not html:
        return []

    results = []
    title_re = re.compile(r'<h3[^>]*>(.*?)</h3>', re.DOTALL)
    link_re  = re.compile(r'<a href="(https?://(?!google)[^"&]+)"[^>]*>\s*<h3')
    snip_re  = re.compile(r'<div[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</div>', re.DOTALL)

    titles   = [re.sub(r'<[^>]+>', '', t).strip() for t in title_re.findall(html)]
    links    = link_re.findall(html)
    snippets = [re.sub(r'<[^>]+>', '', s).strip() for s in snip_re.findall(html)]

    for i, title in enumerate(titles):
        if not title or len(title) < 5:
            continue
        results.append({
            "title":   title,
            "url":     links[i] if i < len(links) else "",
            "snippet": snippets[i] if i < len(snippets) else "",
        })
    return results


def is_relevant(title: str, snippet: str = "") -> bool:
    combined = (title + " " + snippet).lower()
    title_l  = title.lower()

    role_kws = [
        "coo", "chief operating", "head of trading", "chief trading",
        "head of electronic trading", "head of strategy", "chief strategy",
        "market structure", "systematic execution", "head of markets",
        "strategy & business", "strategy and business", "global markets coo",
    ]
    if not any(kw in combined for kw in role_kws):
        return False
    if not any(s in combined for s in SENIORITY):
        return False
    if any(ex in title_l for ex in EXCLUDE):
        return False

    # Skip non-job content
    skip = ["how to", "what is", "guide to", "tips for", "review",
            "interview questions", "definition", "explained", "history of"]
    if any(p in title_l for p in skip):
        return False

    return True


# ── SCANNING ─────────────────────────────────────────────────────────────────

def scan_firm(firm_name: str) -> list:
    results = []
    # Use first word of firm name for loose matching (e.g. "JPMorgan" not "JPMorgan Asset Management")
    firm_word = firm_name.split()[0].lower()

    for role_q in ROLE_QUERIES:
        query = f'{role_q} "{firm_name}" jobs OR careers 2025 OR 2026'
        hits  = google_search(query)
        for h in hits:
            combined = (h["title"] + " " + h["snippet"]).lower()
            if firm_word not in combined:
                continue
            if is_relevant(h["title"], h["snippet"]):
                results.append({
                    "firm":    firm_name,
                    "title":   h["title"],
                    "url":     h["url"] or f"https://www.google.com/search?q={urllib.parse.quote_plus(firm_name+' careers')}",
                    "snippet": h["snippet"][:140],
                    "source":  "Google",
                })
        time.sleep(2)
    return results


def scan_job_board(board: dict) -> list:
    hits    = google_search(board["query"])
    results = []
    for h in hits:
        if board["base_url"] not in h.get("url", ""):
            continue
        if is_relevant(h["title"], h["snippet"]):
            results.append({
                "firm":    board["name"],
                "title":   h["title"],
                "url":     h["url"],
                "snippet": h["snippet"][:140],
                "source":  board["name"],
            })
    time.sleep(2)
    return results


def run_scan() -> list:
    seen      = load_seen()
    all_found = []

    print("\n── Firms ──")
    for firm in TARGET_FIRMS:
        roles = scan_firm(firm)
        print(f"  {firm}: {len(roles)}")
        all_found.extend(roles)
        time.sleep(1)

    print("\n── Job boards ──")
    for board in JOB_BOARD_SEARCHES:
        roles = scan_job_board(board)
        print(f"  {board['name']}: {len(roles)}")
        all_found.extend(roles)
        time.sleep(1)

    unique = {}
    for r in all_found:
        rid = role_id(r["firm"], r["title"])
        if rid not in unique:
            unique[rid] = r

    new_roles = [r for rid, r in unique.items() if rid not in seen]
    seen.update(unique.keys())
    save_seen(seen)

    print(f"\n✓ {len(all_found)} total · {len(unique)} unique · {len(new_roles)} new")
    return new_roles


# ── EMAIL ─────────────────────────────────────────────────────────────────────

def build_email_html(roles: list) -> str:
    today = datetime.date.today().strftime("%B %d, %Y")

    if not roles:
        body = "<p style='color:#666;font-size:14px'>No new matching roles today. Check back tomorrow.</p>"
    else:
        by_firm = {}
        for r in roles:
            by_firm.setdefault(r["firm"], []).append(r)

        rows = ""
        for firm, firm_roles in sorted(by_firm.items()):
            rows += f"""<tr><td colspan="2" style="padding:10px 16px 4px;font-size:11px;
              font-weight:700;color:#1a1a2e;border-top:1px solid #e8e8f0;
              background:#f8f8fc;text-transform:uppercase;letter-spacing:0.6px">
              {firm}</td></tr>"""
            for r in firm_roles:
                snip = f'<div style="font-size:11px;color:#999;margin-top:2px">{r.get("snippet","")}</div>' if r.get("snippet") else ""
                rows += f"""<tr>
                  <td style="padding:8px 16px;font-size:13px;color:#2d2d4a;border-bottom:1px solid #f4f4f8">
                    {r["title"]}{snip}</td>
                  <td style="padding:8px 16px;text-align:right;border-bottom:1px solid #f4f4f8;white-space:nowrap">
                    <a href="{r['url']}" style="color:#4f9cf9;font-size:12px;text-decoration:none;font-weight:500">View →</a>
                  </td></tr>"""

        body = f"""<table width="100%" cellpadding="0" cellspacing="0"
          style="border:1px solid #e8e8f0;border-radius:8px;overflow:hidden">
          <thead><tr style="background:#f0f4ff">
            <th style="padding:9px 16px;text-align:left;font-size:11px;color:#666;font-weight:500;letter-spacing:0.6px">ROLE</th>
            <th></th></tr></thead>
          <tbody>{rows}</tbody></table>"""

    count = f"{len(roles)} new role{'s' if len(roles)!=1 else ''} found"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f2f8;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:28px 16px">
<table width="580" cellpadding="0" cellspacing="0"
  style="margin:0 auto;background:#fff;border-radius:12px;box-shadow:0 2px 16px rgba(0,0,0,0.08);overflow:hidden">
  <tr><td style="background:#1a1a2e;padding:22px 28px">
    <div style="font-size:19px;font-weight:700;color:#fff">Gavin's Job Scanner</div>
    <div style="font-size:12px;color:#8888aa;margin-top:3px">{today}</div>
  </td></tr>
  <tr><td style="background:#eef3ff;padding:11px 28px;border-bottom:1px solid #e0e8ff">
    <span style="font-size:14px;color:#4f9cf9;font-weight:700">{count}</span>
    <span style="font-size:12px;color:#888;margin-left:8px">across 30 firms &amp; job boards</span>
  </td></tr>
  <tr><td style="padding:22px 28px">{body}</td></tr>
  <tr><td style="padding:14px 28px;border-top:1px solid #f0f0f8">
    <div style="font-size:11px;color:#bbb;margin-bottom:6px">Quick searches</div>
    <a href="https://www.efinancialcareers.com/jobs/chief-operating-officer?location=New+York"
      style="font-size:12px;color:#4f9cf9;text-decoration:none;margin-right:14px">eFinancialCareers ↗</a>
    <a href="https://www.indeed.com/jobs?q=COO+trading+finance&l=New+York%2C+NY&sort=date"
      style="font-size:12px;color:#4f9cf9;text-decoration:none;margin-right:14px">Indeed ↗</a>
    <a href="https://www.linkedin.com/jobs/search/?keywords=COO+%22hedge+fund%22&location=New+York&f_E=6&sortBy=DD"
      style="font-size:12px;color:#4f9cf9;text-decoration:none">LinkedIn ↗</a>
  </td></tr>
  <tr><td style="background:#f8f8fc;padding:10px 28px;border-top:1px solid #eee">
    <div style="font-size:10px;color:#bbb">GitHub Actions scanner · psychic-doodle ·
      <a href="https://github.com/sweeneygavin-byte/psychic-doodle" style="color:#bbb">View on GitHub</a>
    </div>
  </td></tr>
</table></td></tr></table></body></html>"""


def send_email(roles: list):
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print(f"⚠ No email credentials set. Would have sent {len(roles)} roles to {EMAIL_TO}")
        return

    today   = datetime.date.today().strftime("%B %d, %Y")
    subject = f"Job Scanner: {len(roles)} new role{'s' if len(roles)!=1 else ''} — {today}"

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    plain = f"Gavin's Job Scanner — {today}\n{len(roles)} new roles\n\n"
    for r in roles:
        plain += f"• {r['firm']}: {r['title']}\n  {r['url']}\n\n"
    if not roles:
        plain = f"Gavin's Job Scanner — {today}\nNo new roles today."

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(build_email_html(roles), "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo(); s.starttls()
            s.login(EMAIL_FROM, EMAIL_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"✓ Email sent to {EMAIL_TO}")
    except Exception as e:
        print(f"✗ Email failed: {e}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("Gavin's Job Scanner v2")
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC"))
    print("=" * 55)

    new_roles = run_scan()

    if new_roles:
        print(f"\n{len(new_roles)} new role(s) found:")
        for r in new_roles:
            print(f"  • [{r['firm']}] {r['title']}")
    else:
        print("\nNo new roles since last run.")

    send_email(new_roles)
    print("\nDone.")


if __name__ == "__main__":
    main()
