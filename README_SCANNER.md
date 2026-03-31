# Gavin's Job Scanner — Setup Guide

Scans 30 target firm careers pages and job boards daily.
Sends an email digest of new COO, Head of Trading, Head of Strategy,
and MD Market Structure roles every weekday morning at 7am ET.

---

## Files in this scanner

| File | What it does |
|------|-------------|
| `scanner.py` | Main script — fetches pages, finds roles, sends email |
| `requirements.txt` | Python dependencies (none needed beyond stdlib) |
| `.github/workflows/daily-scan.yml` | GitHub Actions — runs the scanner on a schedule |
| `seen_roles.json` | Auto-generated — tracks roles already emailed so you don't get duplicates |

---

## Step 1 — Add these files to your repo

In GitHub Desktop:
1. Copy `scanner.py` and `requirements.txt` into your `psychic-doodle` folder
2. Create a folder called `.github` inside your repo folder
3. Inside `.github`, create another folder called `workflows`
4. Copy `daily-scan.yml` into `.github/workflows/`
5. In GitHub Desktop, commit all files with message: `Add job scanner`
6. Click Push origin

Your repo structure should look like:
```
psychic-doodle/
├── gavin_tracker.html
├── scanner.py
├── requirements.txt
└── .github/
    └── workflows/
        └── daily-scan.yml
```

---

## Step 2 — Set up Gmail for sending emails

The scanner uses Gmail to send you the daily digest.
You need to create an **App Password** (not your regular Gmail password).

1. Go to your Google Account → **Security**
2. Make sure **2-Step Verification** is turned ON
3. Search for **"App passwords"** in the security settings
4. Click "App passwords" → Select app: **Mail** → Select device: **Other**
5. Type "Job Scanner" → Click **Generate**
6. Copy the 16-character password shown (e.g. `abcd efgh ijkl mnop`)
   — you'll need this in Step 3

---

## Step 3 — Add your email credentials as GitHub Secrets

GitHub Secrets keep your password out of your code.

1. Go to **github.com/your-username/psychic-doodle**
2. Click **Settings** (top menu of the repo)
3. In the left sidebar click **Secrets and variables** → **Actions**
4. Click **New repository secret** and add each of these:

| Secret name | Value |
|-------------|-------|
| `EMAIL_FROM` | Your Gmail address e.g. `yourname@gmail.com` |
| `EMAIL_TO` | Where to send results e.g. `sweeney_gavin@hotmail.com` |
| `EMAIL_PASSWORD` | The 16-char App Password from Step 2 (no spaces) |

---

## Step 4 — Test it manually

Before waiting for the 7am schedule, trigger a manual run:

1. Go to **github.com/your-username/psychic-doodle**
2. Click the **Actions** tab
3. Click **Daily Job Scanner** in the left list
4. Click **Run workflow** → **Run workflow** (green button)
5. Watch the run — click it to see the live log
6. Check your inbox for the email digest

If the run goes green ✓ and you get an email, you're all set.

---

## Troubleshooting

**Run fails with "authentication error"**
→ Check your App Password — make sure you copied it without spaces

**Run succeeds but no email arrives**
→ Check your spam folder
→ Confirm EMAIL_FROM and EMAIL_TO secrets are set correctly

**No roles found every day**
→ This is normal if you've already seen everything — the scanner only
  reports *new* roles not seen in previous runs
→ Delete `seen_roles.json` from your repo to reset and see everything again

**Want to test locally first?**
```bash
# Set your credentials in your terminal temporarily
export EMAIL_FROM="yourname@gmail.com"
export EMAIL_TO="sweeney_gavin@hotmail.com"
export EMAIL_PASSWORD="your-app-password"

# Run the scanner
python scanner.py
```

---

## Customising the scanner

**Change the schedule**
Edit the cron line in `daily-scan.yml`:
```yaml
- cron: '0 12 * * 1-5'   # Weekdays 7am ET (noon UTC)
- cron: '0 12 * * *'     # Every day including weekends
- cron: '0 8 * * 1-5'    # Weekdays 8am UTC (4am ET — earlier)
```

**Add more keywords**
Edit the `KEYWORDS` list in `scanner.py`:
```python
KEYWORDS = [
    "chief operating officer",
    "head of trading",
    # Add yours here:
    "chief revenue officer",
    "head of fixed income",
]
```

**Add more firms**
Edit the `TARGET_FIRMS` list in `scanner.py`:
```python
TARGET_FIRMS = [
    ...
    {"name": "New Firm", "careers_url": "https://newfirm.com/careers"},
]
```

---

## How it works

1. GitHub Actions spins up a free Linux machine every weekday at 7am ET
2. It runs `scanner.py`
3. The script fetches each careers page and job board, strips the HTML,
   and looks for text that matches your keywords and seniority signals
4. Any role not seen in a previous run gets added to the email
5. The list of seen roles is saved back to `seen_roles.json` in your repo
6. The email digest lands in your inbox
7. The Linux machine shuts down — costs nothing

Total GitHub Actions usage: ~3 minutes/day × 22 weekdays = ~66 min/month
GitHub free tier: 2,000 min/month — well within limits.
