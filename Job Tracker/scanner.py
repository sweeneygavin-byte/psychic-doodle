"""
Gavin's Job Scanner
-------------------
Scans target firm careers pages and job boards daily for matching senior roles.
Sends an email digest of new listings each morning.

Setup: see README_SCANNER.md
"""

import os
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

KEYWORDS = [
    "chief operating officer", "coo",
    "head of trading", "chief trading officer", "head of electronic trading",
    "head of strategy", "chief strategy officer",
    "md, strategy", "managing director, strategy",
    "strategy & business development", "strategy and business development",
    "market structure", "systematic execution",
    "head of markets", "global markets coo",
]

# Only surface roles that contain at least one seniority signal
SENIORITY_SIGNALS = [
    "managing director", "md,", "md ", "chief", "head of",
    "director", "vice president", "vp,", "partner", "president"
]

# Roles that are definitely too junior — skip these
EXCLUDE_TERMS = [
    "analyst", "associate", "intern", "graduate", "junior",
    "assistant", "coordinator", "specialist", "administrator"
]

TARGET_FIRMS = [
    {"name": "Two Sigma",                   "careers_url": "https://www.twosigma.com/careers/"},
    {"name": "D.E. Shaw",                   "careers_url": "https://www.deshaw.com/careers"},
    {"name": "Renaissance Technologies",    "careers_url": "https://www.rentec.com/Careers.action"},
    {"name": "AQR Capital",                 "careers_url": "https://www.aqr.com/About-Us/Careers"},
    {"name": "WorldQuant",                  "careers_url": "https://www.worldquant.com/career-listing/"},
    {"name": "Citadel",                     "careers_url": "https://www.citadel.com/careers/"},
    {"name": "Point72",                     "careers_url": "https://www.point72.com/careers/"},
    {"name": "Millennium Management",       "careers_url": "https://www.mlp.com/careers.html"},
    {"name": "Balyasny Asset Management",   "careers_url": "https://www.balyasny.com/careers"},
    {"name": "ExodusPoint Capital",         "careers_url": "https://www.exoduspoint.com/careers"},
    {"name": "Marshall Wace",               "careers_url": "https://www.mwam.com/join-us/"},
    {"name": "Capula Investment Management","careers_url": "https://careers.capulaglobal.com/"},
    {"name": "Vanguard",                    "careers_url": "https://www.vanguardjobs.com/"},
    {"name": "Fidelity Investments",        "careers_url": "https://jobs.fidelity.com/"},
    {"name": "State Street Global Advisors","careers_url": "https://careers.statestreet.com/"},
    {"name": "Wellington Management",       "careers_url": "https://www.wellington.com/en/careers"},
    {"name": "Nuveen / TIAA",               "careers_url": "https://careers.tiaa.org/"},
    {"name": "JPMorgan",                    "careers_url": "https://careers.jpmorgan.com/"},
    {"name": "Goldman Sachs",               "careers_url": "https://www.goldmansachs.com/careers/"},
    {"name": "Morgan Stanley",              "careers_url": "https://www.morganstanley.com/people-opportunities/"},
    {"name": "Bank of America",             "careers_url": "https://careers.bankofamerica.com/"},
    {"name": "Barclays",                    "careers_url": "https://search.jobs.barclays/"},
    {"name": "Citigroup",                   "careers_url": "https://jobs.citi.com/"},
    {"name": "UBS",                         "careers_url": "https://www.ubs.com/global/en/careers.html"},
    {"name": "Wells Fargo",                 "careers_url": "https://www.wellsfargo.com/about/careers/"},
    {"name": "MarketAxess",                 "careers_url": "https://www.marketaxess.com/about/careers"},
    {"name": "Tradeweb",                    "careers_url": "https://www.tradeweb.com/careers/"},
    {"name": "Virtu Financial",             "careers_url": "https://www.virtu.com/careers/"},
    {"name": "Bloomberg",                   "careers_url": "https://www.bloomberg.com/careers/"},
    {"name": "ION Group",                   "careers_url": "https://iongroup.com/careers/"},
]

# Job board search URLs (public, no login required)
JOB_BOARDS = [
    {
        "name": "eFinancialCareers — COO",
        "url": "https://www.efinancialcareers.com/jobs/chief-operating-officer?location=New+York",
    },
    {
        "name": "eFinancialCareers — Head of Trading",
        "url": "https://www.efinancialcareers.com/jobs/head-of-trading?location=New+York",
    },
    {
        "name": "eFinancialCareers — Strategy",
        "url": "https://www.efinancialcareers.com/jobs/head-of-strategy?location=New+York",
    },
    {
        "name": "Indeed — COO Trading Finance NY",
        "url": "https://www.indeed.com/jobs?q=COO+trading+finance&l=New+York%2C+NY&sort=date&fromage=1",
    },
    {
        "name": "Indeed — Head of Strategy Finance NY",
        "url": "https://www.indeed.com/jobs?q=%22head+of+strategy%22+finance&l=New+York%2C+NY&sort=date&fromage=1",
    },
    {
        "name": "Indeed — Head of Trading NY",
        "url": "https://www.indeed.com/jobs?q=%22head+of+trading%22&l=New+York%2C+NY&sort=date&fromage=1",
    },
]

# File to track already-seen roles across runs
SEEN_ROLES_FILE = "seen_roles.json"

# Email config — loaded from environment variables (set as GitHub Secrets)
EMAIL_FROM    = os.environ.get("EMAIL_FROM", "")
EMAIL_TO      = os.environ.get("EMAIL_TO", "sweeney_gavin@hotmail.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))


# ── HELPERS ───────────────────────────────────────────────────────────────────

def role_id(firm_name: str, title: str) -> str:
    """Stable ID for a role so we can deduplicate across runs."""
    raw = f"{firm_name.lower()}::{title.lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_seen() -> set:
    if os.path.exists(SEEN_ROLES_FILE):
        with open(SEEN_ROLES_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_ROLES_FILE, "w") as f:
        json.dump(list(seen), f, indent=2)


def fetch_page(url: str, timeout: int = 15) -> str:
    """Fetch a URL and return its text content. Returns '' on failure."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            # Try utf-8 first, fall back to latin-1
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")
    except Exception as e:
        print(f"  ⚠ Could not fetch {url}: {e}")
        return ""


def strip_tags(html: str) -> str:
    """Very lightweight HTML tag stripper — no dependencies needed."""
    import re
    # Remove scripts and styles entirely
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove remaining tags
    html = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def is_relevant(title: str) -> bool:
    """Return True if the title looks like a senior matching role."""
    t = title.lower()
    # Must match at least one keyword
    if not any(kw in t for kw in KEYWORDS):
        return False
    # Must have at least one seniority signal
    if not any(s in t for s in SENIORITY_SIGNALS):
        return False
    # Must not be clearly junior
    if any(ex in t for ex in EXCLUDE_TERMS):
        return False
    return True


def extract_titles_from_text(text: str, firm_name: str) -> list[dict]:
    """
    Pull candidate job titles out of a block of plain text.
    Looks for lines that look like job titles near seniority keywords.
    """
    import re
    results = []
    # Split into chunks of reasonable length — potential title candidates
    lines = [l.strip() for l in re.split(r"[\n|•·,]", text) if l.strip()]
    for line in lines:
        # Titles are usually 3–80 chars
        if not (3 < len(line) < 80):
            continue
        if is_relevant(line):
            results.append({
                "firm": firm_name,
                "title": line,
                "source": "careers page",
            })
    return results


# ── SCANNING ─────────────────────────────────────────────────────────────────

def scan_firm(firm: dict) -> list[dict]:
    """Scan a single firm's careers page for matching roles."""
    print(f"  Scanning {firm['name']}...")
    html = fetch_page(firm["careers_url"])
    if not html:
        return []
    text = strip_tags(html)
    roles = extract_titles_from_text(text, firm["name"])
    # Add the direct link
    for r in roles:
        r["url"] = firm["careers_url"]
    return roles


def scan_job_board(board: dict) -> list[dict]:
    """Scan a single job board URL for matching roles."""
    print(f"  Scanning {board['name']}...")
    html = fetch_page(board["url"])
    if not html:
        return []
    text = strip_tags(html)
    roles = extract_titles_from_text(text, board["name"])
    for r in roles:
        r["source"] = board["name"]
        r["url"] = board["url"]
    return roles


def run_scan() -> list[dict]:
    """Run the full scan across all firms and boards. Returns new roles only."""
    seen = load_seen()
    all_found = []

    print("\n── Scanning target firm careers pages ──")
    for firm in TARGET_FIRMS:
        roles = scan_firm(firm)
        all_found.extend(roles)
        time.sleep(1.5)  # Be polite — don't hammer servers

    print("\n── Scanning job boards ──")
    for board in JOB_BOARDS:
        roles = scan_job_board(board)
        all_found.extend(roles)
        time.sleep(1.5)

    # Deduplicate within this run
    unique = {}
    for r in all_found:
        rid = role_id(r["firm"], r["title"])
        if rid not in unique:
            unique[rid] = r

    # Filter to only genuinely new roles
    new_roles = [r for rid, r in unique.items() if rid not in seen]

    # Update seen set
    seen.update(unique.keys())
    save_seen(seen)

    print(f"\n✓ Found {len(all_found)} total matches, {len(new_roles)} new since last run")
    return new_roles


# ── EMAIL ─────────────────────────────────────────────────────────────────────

def build_email_html(roles: list[dict]) -> str:
    today = datetime.date.today().strftime("%B %d, %Y")

    if not roles:
        body = "<p style='color:#666'>No new matching roles found today. Check back tomorrow.</p>"
    else:
        rows = ""
        # Group by firm
        by_firm: dict[str, list] = {}
        for r in roles:
            by_firm.setdefault(r["firm"], []).append(r)

        for firm, firm_roles in sorted(by_firm.items()):
            rows += f"""
            <tr>
              <td colspan="2" style="padding:12px 16px 4px;font-size:13px;font-weight:600;
                color:#1a1a2e;border-top:1px solid #e8e8f0;background:#f8f8fc">
                {firm}
              </td>
            </tr>"""
            for r in firm_roles:
                source_label = r.get("source", "careers page")
                rows += f"""
            <tr>
              <td style="padding:8px 16px;font-size:13px;color:#2d2d4a;width:70%">
                {r['title']}
                <div style="font-size:11px;color:#888;margin-top:2px">{source_label}</div>
              </td>
              <td style="padding:8px 16px;text-align:right">
                <a href="{r['url']}" style="font-size:12px;color:#4f9cf9;
                  text-decoration:none;font-weight:500">View →</a>
              </td>
            </tr>"""

        body = f"""
        <table width="100%" cellpadding="0" cellspacing="0"
          style="border:1px solid #e8e8f0;border-radius:8px;overflow:hidden;
                 font-family:'DM Sans',Arial,sans-serif">
          <thead>
            <tr style="background:#f0f4ff">
              <th style="padding:10px 16px;text-align:left;font-size:12px;
                color:#555;font-weight:500;letter-spacing:0.5px">ROLE</th>
              <th style="padding:10px 16px;text-align:right;font-size:12px;
                color:#555;font-weight:500;letter-spacing:0.5px">LINK</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""

    count_label = f"{len(roles)} new role{'s' if len(roles) != 1 else ''} found"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td style="padding:32px 24px">
      <table width="600" cellpadding="0" cellspacing="0"
        style="margin:0 auto;background:#fff;border-radius:12px;
               box-shadow:0 2px 12px rgba(0,0,0,0.06);overflow:hidden">

        <!-- HEADER -->
        <tr>
          <td style="background:#1a1a2e;padding:24px 28px">
            <div style="font-size:20px;font-weight:600;color:#fff;letter-spacing:-0.3px">
              Gavin's Job Scanner
            </div>
            <div style="font-size:13px;color:#8888aa;margin-top:4px">{today}</div>
          </td>
        </tr>

        <!-- SUMMARY BAR -->
        <tr>
          <td style="background:#f0f4ff;padding:12px 28px;border-bottom:1px solid #e8e8f0">
            <span style="font-size:14px;color:#4f9cf9;font-weight:600">{count_label}</span>
            <span style="font-size:13px;color:#888;margin-left:8px">
              across 30 target firms and job boards
            </span>
          </td>
        </tr>

        <!-- BODY -->
        <tr>
          <td style="padding:24px 28px">
            {body}
          </td>
        </tr>

        <!-- QUICK LINKS -->
        <tr>
          <td style="padding:16px 28px;border-top:1px solid #f0f0f8">
            <div style="font-size:12px;color:#aaa;margin-bottom:8px">Quick searches</div>
            <div style="display:flex;gap:12px;flex-wrap:wrap">
              <a href="https://www.efinancialcareers.com/jobs/chief-operating-officer?location=New+York"
                style="font-size:12px;color:#4f9cf9;text-decoration:none">eFinancialCareers ↗</a>
              <a href="https://www.indeed.com/jobs?q=COO+trading+finance&l=New+York%2C+NY&sort=date"
                style="font-size:12px;color:#4f9cf9;text-decoration:none">Indeed ↗</a>
              <a href="https://www.linkedin.com/jobs/search/?keywords=COO+%22hedge+fund%22&location=New+York&f_E=6&sortBy=DD"
                style="font-size:12px;color:#4f9cf9;text-decoration:none">LinkedIn ↗</a>
            </div>
          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td style="background:#f8f8fc;padding:16px 28px;border-top:1px solid #e8e8f0">
            <div style="font-size:11px;color:#aaa">
              Sent by your GitHub Actions scanner · psychic-doodle repo ·
              <a href="https://github.com" style="color:#aaa">View on GitHub</a>
            </div>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_email(roles: list[dict]):
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("⚠ No email credentials set — skipping email. Set EMAIL_FROM and EMAIL_PASSWORD secrets.")
        return

    today = datetime.date.today().strftime("%B %d, %Y")
    subject = f"Job Scanner: {len(roles)} new role{'s' if len(roles) != 1 else ''} — {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    # Plain text fallback
    if roles:
        plain_lines = [f"Job Scanner — {today}", f"{len(roles)} new roles found\n"]
        for r in roles:
            plain_lines.append(f"• {r['firm']}: {r['title']}")
            plain_lines.append(f"  {r['url']}\n")
        plain = "\n".join(plain_lines)
    else:
        plain = f"Job Scanner — {today}\nNo new roles found today."

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(build_email_html(roles), "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"✓ Email sent to {EMAIL_TO}")
    except Exception as e:
        print(f"✗ Failed to send email: {e}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("Gavin's Job Scanner")
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    new_roles = run_scan()

    if new_roles:
        print("\nNew roles found:")
        for r in new_roles:
            print(f"  • [{r['firm']}] {r['title']}")
    else:
        print("\nNo new roles found today.")

    send_email(new_roles)
    print("\nDone.")


if __name__ == "__main__":
    main()
