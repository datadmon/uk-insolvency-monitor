# UK Insolvency Monitor: get alerted when a customer appears in The Gazette

Watch a list of UK companies (your **customers, suppliers, debtors or portfolio**) and get an alert the morning one of them appears in **The Gazette** with a **winding-up petition, winding-up order or administration**. Matching is by **Companies House number**, with the company name as a fallback, and each alert carries the court, case number, petitioner (for example HMRC) and hearing date.

It is a credit-control and risk tool you run yourself: a GitHub Actions workflow in your copy of this repository checks the new notices every day, keeps a history in CSV and tells you by GitHub issue, Slack, Discord or Telegram. No scraper to maintain, no Companies House API key, no subscription.

![Outputs](https://img.shields.io/badge/output-GitHub%20issue%20%7C%20Slack%20%7C%20Telegram%20%7C%20Discord%20%7C%20CSV-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Why the Gazette

A winding-up petition is advertised in The Gazette before the court hearing, so it is often the first public sign that a creditor is trying to wind a company up; a winding-up order or an administration means you should stop supplying on credit and file your claim. In a three-day sample on 26 October 2026 the default notice types produced 150 notices, and **62 of the 80 winding-up petitions were brought by HMRC**.

## What an alert looks like

From a real run on 26 October 2026 (the example [`watchlist.csv`](watchlist.csv) holds two companies taken from that week's notices, so the first run has something to show):

| Published | Company | Number | Notice | Court / case | Matched by |
|---|---|---|---|---|---|
| 2026-10-25 | [YORK WEST 3 LIMITED](https://www.thegazette.co.uk/notice/5237372) | 12511873 | Winding-up order | High Court Of Justice 006487 of 2026 | company number |
| 2026-10-25 | [BENTLEY CARTER APARTMENTS LTD](https://www.thegazette.co.uk/notice/5236955) | 08083568 | Winding-up order | High Court Of Justice 006671 of 2026 | name |

Petitions carry more: for example [NINE MINE IRON LTD](https://www.thegazette.co.uk/notice/5237233) (09915949), petition presented 28 September 2026 by SPECIALITY STEEL UK LIMITED (IN LIQUIDATION), hearing 18 November 2026 at the Rolls Building, High Court case CR-2026-007507. Matches accumulate in [`data/matches.csv`](data/matches.csv); [`data/latest.md`](data/latest.md) shows the last run.

## Set it up in five minutes

1. Click **Use this template → Create a new repository**. Make it **private** if your watchlist is confidential.
2. Create a free [Apify](https://apify.com) account, copy your API token from **Console → Settings → Integrations**, and add it in your repository under **Settings → Secrets and variables → Actions** as `APIFY_TOKEN`.
3. Add the workflow: **Add file → Create new file**, name it `.github/workflows/insolvency-monitor.yml`, paste the contents of [`setup/insolvency-monitor.yml`](setup/insolvency-monitor.yml) and commit.
4. Replace the example rows in [`watchlist.csv`](watchlist.csv) with your companies (`company_number,company_name,note`; an export from your accounting or CRM system works), then run **Actions → UK insolvency monitor → Run workflow** once. It then runs every morning.

## Configuration

```json
{
  "watchlist": "watchlist.csv",
  "noticeTypes": ["2450", "2452", "2410"],
  "publishedWithinDays": 3,
  "maxNoticesPerRun": 1000,
  "maxCostPerRunUsd": 2,
  "reportAllNotices": false,
  "notify": {"githubIssue": true}
}
```

| Code | Gazette notice type | Typical volume (7 days to 26 Oct 2026) |
|---|---|---:|
| `2450` | Petitions to wind up (companies) | 129 |
| `2452` | Winding-up orders | 82 |
| `2410` | Appointment of administrators | 32 |
| `2441` | Resolutions for winding up (voluntary liquidation) | 351 |
| `2432`, `2443` | Appointment of liquidators | 209, 366 |
| `2442` | Meetings of creditors | 118 |

The default watches the three court-driven and administration notices. Add `2441` to catch voluntary liquidations too. `reportAllNotices: true` also lists every new notice in `data/latest.md`, which turns the repository into a daily UK insolvency feed for prospecting or market monitoring.

## Notifications

- **GitHub issue** (on by default): one issue per run with matches; GitHub emails you if you watch the repository.
- **Slack**: incoming webhook URL as the secret `SLACK_WEBHOOK_URL`.
- **Discord**: channel webhook URL as `DISCORD_WEBHOOK_URL`.
- **Telegram**: `TELEGRAM_BOT_TOKEN` (from @BotFather) and `TELEGRAM_CHAT_ID`.

Nothing is sent on days without a match; the check itself is logged in the Actions run.

## What it costs

The notices come from the [UK Gazette Insolvency Notices Scraper](https://apify.com/data_daemon/uk-gazette-insolvency-notices) on Apify, which charges per notice: $0.002 for the notice plus $0.003 for its structured data (company number, court, petitioner, hearing), i.e. **$5 per 1,000 notices** on the free plan (26 October 2026). The default three notice types run to about 240 notices a week, roughly **$5 a month** whatever the size of your watchlist; Apify's free plan includes $5 of usage every month. Adding voluntary liquidations (`2441`) brings it to about $13 a month. Notices already checked by an earlier run are skipped and **not charged again**. `maxCostPerRunUsd` caps every run.

## How it works

1. The Actor reads the Gazette's insolvency feed for the chosen notice types in the last `publishedWithinDays` days, with **only new notices since the last run** switched on and a memory name unique to your repository, so each notice is fetched once.
2. For every notice it reads the Gazette's linked data: company number and name, registered office, nature of business, court, case number, petitioner, hearing date and the insolvency practitioner.
3. `insolvency_monitor.py` matches the notices against your watchlist by Companies House number (zero-padded, `SC`/`NI`/`OC` prefixes kept) and, for rows without a number, by normalised name (LTD = LIMITED, punctuation ignored).

Run it locally with `python insolvency_monitor.py` (or `--dry-run`); Python 3.9+, standard library only.

## FAQ

**Is there a Gazette API?**
The Gazette publishes its notices as open data (Crown copyright, Open Government Licence v3.0) with a search feed and linked data per notice. The Actor turns that into clean rows with the company number, which is what a watchlist needs.

**Does it cover Scotland and Northern Ireland?**
Yes. In the 26 October 2026 sample, 13 of the 150 notices concerned Scottish companies (`SC` numbers) and 3 Northern Irish ones (`NI`); put the numbers in your watchlist as Companies House shows them.

**Can I monitor personal insolvencies?**
This tool is built for companies. The Actor can read personal insolvency notices (for example bankruptcy orders, `2503`), but those contain personal data with reuse restrictions, so they are not part of the default.

**How quickly will I know?**
The workflow runs once a day; a notice published that day is picked up the next morning.

## Related

- [UK Gazette Insolvency Notices Scraper](https://apify.com/data_daemon/uk-gazette-insolvency-notices) on Apify: run the same search by hand, from the API, or with an Apify schedule and its Slack or email integrations.
- [Daily UK winding-up petitions feed](https://datadmon.github.io/guides/uk-winding-up-petitions-daily-feed/): guide to the notice types and fields.
- [apify-data-actors-examples](https://github.com/datadmon/apify-data-actors-examples): Python, Node.js, curl and n8n examples.

## More templates by Daemon Data

- [india-job-alerts](https://github.com/datadmon/india-job-alerts): daily new-job alerts from IIMJobs, Hirist, Foundit and Instahyre.
- [uk-insolvency-monitor](https://github.com/datadmon/uk-insolvency-monitor): alerts when a watchlist company appears in The Gazette (winding-up petitions, administrations).
- [india-ipo-gmp-tracker](https://github.com/datadmon/india-ipo-gmp-tracker): daily IPO GMP table, GMP history and Telegram alerts.

Contains public sector information licensed under the Open Government Licence v3.0 (The Gazette). Not affiliated with The Gazette or Companies House. This tool alerts you to published notices; it is not legal or credit advice.
