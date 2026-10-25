"""UK insolvency monitor: alert when a company on your watchlist appears in The Gazette.

    export APIFY_TOKEN=...              # https://console.apify.com/settings/integrations
    python insolvency_monitor.py        # reads config.json + watchlist.csv, writes data/, sends alerts on matches
    python insolvency_monitor.py --dry-run

Each run fetches the new corporate insolvency notices from The Gazette (winding-up petitions, winding-up orders,
administrations by default) through an Apify Actor, with the company number, court, case number, petitioner and
hearing date, and checks them against watchlist.csv by Companies House number (and by name as a fallback).
"Only new notices" mode means each notice is fetched and charged once. Standard library only; Python 3.9+.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.apify.com/v2"
ACTOR = "data_daemon~uk-gazette-insolvency-notices"  # https://apify.com/data_daemon/uk-gazette-insolvency-notices
NOTICE_TYPES = {"2450": "Petition to wind up", "2452": "Winding-up order", "2410": "Appointment of administrators",
                "2441": "Resolution for winding up", "2432": "Appointment of liquidators", "2443": "Appointment of liquidators",
                "2442": "Meeting of creditors", "2433": "Notice to creditors"}
COLUMNS = ["published", "matchedBy", "watchlistName", "note", "companyNumber", "companyName", "noticeType", "court", "caseNumber",
           "petitioner", "hearingDate", "postcode", "url", "noticeId"]
ROOT = Path(__file__).resolve().parent
SUFFIXES = re.compile(r"\b(LIMITED|LTD|PLC|LLP|L\.L\.P|COMPANY|CO|THE|UK|U\.K)\b\.?")


def request(method, url, token, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.load(res)


def run_actor(run_input, token, max_charge_usd):
    query = urllib.parse.urlencode({"timeout": 1800, "maxTotalChargeUsd": max_charge_usd})
    run = request("POST", f"{API}/acts/{ACTOR}/runs?{query}", token, run_input)["data"]
    while run["status"] in ("READY", "RUNNING"):
        time.sleep(5)
        run = request("GET", f"{API}/actor-runs/{run['id']}", token)["data"]
    if run["status"] != "SUCCEEDED":
        raise RuntimeError(f"run {run['id']} ended {run['status']}: {run.get('statusMessage')}")
    items, offset = [], 0
    while True:
        page = request("GET", f"{API}/datasets/{run['defaultDatasetId']}/items?clean=1&format=json&limit=1000&offset={offset}", token)
        items += page
        offset += len(page)
        if len(page) < 1000:
            return items, run.get("statusMessage") or ""


def norm_number(value):
    """Companies House numbers are 8 characters: digits are zero-padded, prefixes such as SC/NI/OC are kept."""
    v = re.sub(r"\s", "", str(value or "")).upper()
    return v.zfill(8) if v.isdigit() else v


def norm_name(value):
    v = re.sub(r"[^A-Z0-9 ]", " ", SUFFIXES.sub(" ", str(value or "").upper().replace("&", " AND ")))
    return " ".join(v.split())


def load_watchlist(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("company_number") or r.get("company_name") or "").strip()]
    by_number = {norm_number(r["company_number"]): r for r in rows if (r.get("company_number") or "").strip()}
    by_name = {norm_name(r["company_name"]): r for r in rows if (r.get("company_name") or "").strip()}
    return rows, by_number, by_name


def match(notices, by_number, by_name):
    out = []
    for n in notices:
        number, name = norm_number(n.get("companyNumber")), norm_name(n.get("companyName") or n.get("title"))
        hit, how = (by_number.get(number), "company number") if number and number in by_number else (by_name.get(name), "name")
        if not hit:
            continue
        out.append({
            "published": n.get("publishedDate") or (n.get("published") or "")[:10],
            "matchedBy": how,
            "watchlistName": hit.get("company_name") or "",
            "note": hit.get("note") or "",
            "companyNumber": n.get("companyNumber") or "",
            "companyName": n.get("companyName") or n.get("title") or "",
            "noticeType": NOTICE_TYPES.get(str(n.get("noticeCode")), str(n.get("noticeCode") or "")),
            "court": n.get("courtName") or "",
            "caseNumber": n.get("caseNumber") or "",
            "petitioner": n.get("petitioner") or "",
            "hearingDate": (n.get("hearingDate") or n.get("dateOfHearing") or "")[:10],
            "postcode": n.get("postcode") or "",
            "url": n.get("url") or "",
            "noticeId": str(n.get("noticeId") or ""),
        })
    return out


def write_outputs(matches, notices, data_dir, report_all):
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "matches.csv"
    known = set()
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            known = {r["noticeId"] for r in csv.DictReader(f)}
    fresh = [m for m in matches if m["noticeId"] not in known]
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            w.writeheader()
        w.writerows(fresh)
    today = dt.date.today().isoformat()
    lines = [f"# Gazette check, {today}", "", f"{len(notices)} new notice(s) checked, **{len(fresh)} match(es)** on the watchlist. "
             "All matches so far are in [matches.csv](matches.csv).", ""]
    cell = lambda s: str(s).replace("|", "/")
    if fresh:
        lines += ["| Published | Company | Number | Notice | Court / case | Petitioner | Hearing | Matched by |", "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {m['published']} | [{cell(m['companyName'])}]({m['url']}) | {m['companyNumber']} | {m['noticeType']} | "
                  f"{cell(m['court'])} {cell(m['caseNumber'])} | {cell(m['petitioner'])} | {m['hearingDate']} | {m['matchedBy']} |" for m in fresh]
    if report_all and notices:
        lines += ["", "## All new notices", "", "| Published | Company | Number | Notice | Petitioner |", "|---|---|---|---|---|"]
        lines += [f"| {n.get('publishedDate', '')} | [{cell(n.get('companyName') or n.get('title'))}]({n.get('url')}) | {n.get('companyNumber') or ''} | "
                  f"{NOTICE_TYPES.get(str(n.get('noticeCode')), n.get('noticeCode'))} | {cell(n.get('petitioner') or '')} |" for n in notices[:300]]
    (data_dir / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return fresh


def post_json(url, payload, headers=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    urllib.request.urlopen(req, timeout=60).read()


def notify(matches, cfg):
    if not matches:
        return
    text = f"{len(matches)} watchlist compan{'y' if len(matches) == 1 else 'ies'} in The Gazette\n" + "\n".join(
        f"• {m['companyName']} ({m['companyNumber']}): {m['noticeType']}, published {m['published']}"
        f"{', hearing ' + m['hearingDate'] if m['hearingDate'] else ''} {m['url']}" for m in matches[:30])
    channels = []
    if os.environ.get("SLACK_WEBHOOK_URL"):
        channels.append(("Slack", os.environ["SLACK_WEBHOOK_URL"], {"text": text}, None))
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        channels.append(("Discord", os.environ["DISCORD_WEBHOOK_URL"], {"content": text[:1990]}, None))
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        channels.append(("Telegram", f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                         {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text[:4000], "disable_web_page_preview": True}, None))
    repo, gh = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if cfg.get("githubIssue", True) and repo and gh:
        body = "\n".join(f"- **{m['companyName']}** ({m['companyNumber']}, {m['note'] or 'watchlist'}): {m['noticeType']}, "
                         f"{m['court']} {m['caseNumber']}, published {m['published']} [notice]({m['url']})" for m in matches)
        channels.append(("GitHub issue", f"https://api.github.com/repos/{repo}/issues",
                         {"title": f"Gazette: {len(matches)} watchlist match(es) on {dt.date.today().isoformat()}", "body": body},
                         {"Authorization": f"Bearer {gh}", "Accept": "application/vnd.github+json"}))
    for name, url, payload, headers in channels:
        try:  # a broken channel must not lose the run's data
            post_json(url, payload, headers)
            print("notified:", name)
        except urllib.error.URLError as err:
            print(f"could not notify {name}: {err}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    rows, by_number, by_name = load_watchlist(ROOT / cfg.get("watchlist", "watchlist.csv"))
    feed_id = hashlib.sha1((os.environ.get("GITHUB_REPOSITORY") or "local").encode()).hexdigest()[:8]
    types = cfg.get("noticeTypes", ["2450", "2452", "2410"])
    run_input = {
        "service": "insolvency",
        "noticeTypes": types,
        "publishedWithinDays": cfg.get("publishedWithinDays", 3),
        "includeLinkedData": True,  # needed for the company number
        "onlyNewSinceLastRun": True,
        "stateName": f"monitor-{feed_id}-" + hashlib.sha1(",".join(sorted(types)).encode()).hexdigest()[:8],
        "maxItems": cfg.get("maxNoticesPerRun", 1000),
    }
    print(f"watchlist: {len(rows)} companies ({len(by_number)} with a company number)")
    if a.dry_run:
        print(json.dumps(run_input))
        return
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("Set APIFY_TOKEN (Apify Console > Settings > Integrations). In GitHub: Settings > Secrets > Actions.")
    notices, status = run_actor(run_input, token, cfg.get("maxCostPerRunUsd", 2))
    print(f"{len(notices)} new notices | {status}")
    matches = match(notices, by_number, by_name)
    fresh = write_outputs(matches, notices, ROOT / cfg.get("dataDir", "data"), cfg.get("reportAllNotices", False))
    print(f"{len(fresh)} new watchlist match(es)")
    notify(fresh, cfg.get("notify", {}))


if __name__ == "__main__":
    main()
