# INDEED.md — Indeed board scraping notes

Strategy: poll search URLs (sorted by date), no login, no pagination.
Dedupe via `jobkey` against `seen_ids`. Stores direct `/viewjob?jk=` links with
snippets from search cards (no secondary detail-page fetches).

## Search URLs
Configurable via `INDEED_SEARCH_URL` / `INDEED_SEARCH_URLS` in `.env` (single URL or JSON array of URLs).
Example:
https://eg.indeed.com/jobs?q=frontend&l=egypt&sort=date&fromage=1&from=searchOnDesktopSerp&vjk=e6100dd5bfdeb85f

- No login needed for page 1; pagination IS login-gated → don't paginate.
- First page holds ~15 jobs (newest first). `sort=date` keeps new jobs at top.

## Gating
- Plain curl with CF cookies → 403 "Security Check" (Cloudflare captcha).
- Must use scrapling stealth session with `solve_cloudflare=True`, persistent
  profile (`indeedprofile/`), CDP pattern like the other boards.

## Data source in HTML: Search page job cards blob
Marker: `window.mosaic.providerData["mosaic-provider-jobcards"] = {...};`
Path: `metaData.mosaicProviderJobCardsModel.results` (array)
Fields per job:
- `jobkey` (Indeed unique id → external_id)
- `displayTitle` / `normTitle` (title)
- `company`
- `formattedLocation` / `jobLocationCity` (location)
- `extractedSalary` → {max, min, type} e.g. {"max":50000,"min":18000,"type":"MONTHLY"}
  - CAVEAT: some jobs have `{"currency":"","salaryTextFormatted":false}` → None
- `jobTypes` (array, e.g. ["Full-time"])
- `pubDate` / `createDate` (unix ms → posted_at)
- `snippet` (short HTML summary → description)
- `viewJobLink` (relative URL)

## Extraction approach
- Marker regex + brace balancing (like Wuzzuf `_extract_state`) — NOT
  non-greedy `({.*?});` regexes: nested braces break them.
- `re.search(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*', html)`
  then balance braces to the closing `};`.
- Use `page.content()` (stealth isolated contexts kill `evaluate`, learned on Wuzzuf).

## Job dict mapping
source="indeed", external_id=jobkey, title=displayTitle, company=company,
posted_at=createDate (ms→local `YYYY-MM-DD HH:MM`, TZ=Africa/Cairo; NOTE:
`pubDate` is normalized to midnight — always prefer `createDate`),
description=search card snippet,
link=https://eg.indeed.com/viewjob?jk={key} (canonical — drop the token-laden
`viewJobLink` query string), extra={location, salary min/max/type, jobTypes,
snippet}, scraped_at.

## Offline verification
- Fixture: `markup/indeed/first_page.html` (search page capture)
- `_extract_jobs(search_html, set())` → 15 jobs, non-empty fields, snippet descriptions
