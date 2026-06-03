# Target Company Ingestion Plan

This plan narrows job discovery from "search the whole internet" to "monitor a curated list of target companies." That is a better fit for focused job search and makes automated discovery more reliable.

## Product direction

Instead of broad scraping, the app should support:

```text
User defines target companies
  -> app checks those companies periodically
  -> app finds newly posted relevant jobs
  -> app deduplicates and scores them
  -> app saves high-signal jobs to the tracker
```

This is more useful for users who care about specific large companies, AI labs, infra companies, or high-priority teams.

## Why this direction

Benefits:

- Less noisy than general web search.
- Easier to explain and debug.
- Better deduplication.
- Better company-specific prep later.
- Easier to schedule as a daily cron job.
- Lets us invest in high-value connectors instead of trying to scrape the entire web.

Tradeoff:

- Lower coverage than open-web job discovery.
- Requires users to maintain a watchlist.
- Some large company career sites may still require browser automation.

## Target company config

Add a user-editable config file:

```text
app/memory/target_companies.local.yaml
```

This file should be ignored by Git because it may reflect private job-search preferences.

Public template:

```text
app/memory/target_companies.example.yaml
```

Example shape:

```yaml
target_companies:
  - name: "Example AI"
    priority: "high"
    careers_url: "https://boards.greenhouse.io/exampleai"
    ats: "greenhouse"
    target_keywords:
      - "AI platform"
      - "LLM"
      - "agent"
      - "backend"
      - "infrastructure"
    locations:
      - "Remote"
      - "Seattle"
      - "San Francisco"

  - name: "Example Cloud"
    priority: "medium"
    careers_url: "https://example.com/careers"
    ats: "generic"
    target_keywords:
      - "distributed systems"
      - "workflow"
      - "platform"
```

## Ingestion pipeline

The app should add a new `app/ingestion/` module:

```text
app/ingestion/
  pipeline.py
  normalizer.py
  deduper.py
  sources/
    base.py
    manual.py
    generic_http.py
    browser.py
    greenhouse.py
    lever.py
    ashby.py
```

The core pipeline:

```text
load target companies
  -> choose source connector
  -> fetch raw postings
  -> normalize job shape
  -> deduplicate against tracker
  -> score against profile
  -> save relevant jobs
  -> return scan summary
```

## Common source interface

Every source connector should return the same internal shape.

```python
class JobSource:
    def fetch_jobs(self, company: TargetCompany) -> list[RawJobPosting]:
        ...
```

Normalized posting shape:

```python
class RawJobPosting:
    title: str
    company: str
    source_url: str
    location: str | None
    description: str | None
    posted_at: datetime | None
    source: str
```

This prevents the rest of the app from caring whether a job came from Greenhouse, Lever, a browser page, or manual paste.

## Connector strategy

Build connectors in this order:

1. Manual URL/text
   - Already partially supported.
   - Keeps the app useful for any job page.

2. Generic HTTP connector
   - Works for static pages.
   - Low complexity.
   - Already partially supported via `app/tools/job_fetcher.py`.

3. Greenhouse connector
   - Covers many startups and tech companies.
   - Good first ATS connector because the URL patterns are relatively predictable.

4. Lever connector
   - Also common in tech.
   - Good second ATS connector.

5. Browser connector with Playwright
   - Handles JavaScript-heavy company career pages.
   - Useful for large companies and complex portals.

6. Ashby/Workday connectors
   - Add based on actual target company needs.

## Deduplication

Deduplicate in layers:

1. Exact `source_url` match.
2. Same company + normalized title.
3. Optional fuzzy match later for titles with small wording changes.

Current repo already supports duplicate detection by `source_url`.

## Relevance filtering

Each discovered job should be filtered and scored using:

- user profile
- target roles
- company-specific keywords
- avoid-list
- seniority
- location preferences
- detected skills

Early version can save medium/high matches and ignore low matches.

Later version can create a review queue:

```text
new -> reviewed -> interested -> applied
```

## Cron/scheduled workflow

The scheduled job should eventually run:

```text
daily target company scan
  -> fetch postings
  -> save relevant new jobs
  -> produce summary
```

Example summary:

```text
Target company scan complete:
- 8 companies checked
- 43 postings fetched
- 6 new relevant jobs found
- 3 high priority
- 3 medium priority
- 2 need manual review because page extraction failed
```

Implementation options:

- Local cron.
- APScheduler inside the app.
- GitHub Actions for public/demo runs without private profile data.
- AWS EventBridge/Step Functions later for cloud deployment discussion.

For local-first MVP, start with a manual "Scan now" button before adding cron.

## API surface

Suggested future endpoints:

```http
GET /companies
POST /companies/scan
POST /companies/{company_name}/scan
GET /ingestion/runs
GET /ingestion/runs/{run_id}
```

Optional UI:

- Target companies list.
- Scan now button.
- Last scan status.
- Newly found jobs.
- Jobs needing manual review.

## Next implementation milestone

Build the smallest useful target-company feature:

1. Add `target_companies.example.yaml`.
2. Add ignored `target_companies.local.yaml` pattern.
3. Add target company loader.
4. Add `TargetCompany` and `RawJobPosting` models.
5. Add a generic source interface.
6. Add a manual/generic HTTP source adapter.
7. Add a `POST /companies/scan` endpoint.
8. Show scan results in the UI.

Do not start with cron. First make "Scan now" work, then schedule it.

## Interview framing

A good explanation:

> I initially considered broad job search, but narrowed the scope to a target-company watchlist because my use case values precision over coverage. That let me design a cleaner ingestion pipeline with pluggable source connectors. Instead of writing one scraper per company, I planned reusable connectors for common ATS platforms such as Greenhouse and Lever, plus a browser automation fallback for JavaScript-heavy career sites. The pipeline normalizes postings, deduplicates by source URL and company/title, scores against the user profile, and saves relevant jobs to the tracker. I would add cron only after the manual scan workflow is reliable.

This shows:

- product scope control
- source abstraction
- connector design
- deduplication strategy
- reliability-first scheduling
- practical tradeoff awareness
