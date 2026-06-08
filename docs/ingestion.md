# Job Ingestion

This document explains how CareerPilot turns job URLs into structured job postings. It combines the former fetching tradeoffs, selector-learning notes, and target-company ingestion plan into one place.

## Product Goal

Support reliable single-job analysis now, then later support curated target-company discovery.

```text
job URL
  -> readable posting extraction
  -> structured job facts
  -> semantic analysis
  -> optional tracker save
```

## Why Ingestion Is Hard

Career pages vary widely:

- Some expose readable server-rendered HTML.
- Some include schema.org `JobPosting` JSON-LD.
- Some render the description with JavaScript.
- Some flatten section headings like required/preferred qualifications.
- Some include noisy navigation, related jobs, legal text, or application UI.
- Some block automation or require session state.

No single extractor is reliable, cheap, and broadly compatible.

## Current Layered Strategy

CareerPilot uses a layered strategy for individual URL analysis:

```text
HTTP fetch
  -> JSON-LD JobPosting metadata
  -> Playwright-rendered page sections
  -> learned or reviewed content-root selector
  -> bounded discovery fallback
  -> manual paste fallback
```

### Plain HTTP

Best for static pages and cheap first-pass fetching.

Pros:

- Fast.
- Simple.
- Easy to test.
- Lower operational complexity.

Cons:

- Fails on many JavaScript-rendered career pages.
- Can include noisy page text.
- Cannot interact with the page.

### JSON-LD

Useful for canonical title, company, location, and description when present.

Risk:

JSON-LD can flatten qualification headings. CareerPilot preserves metadata but also uses rendered page sections so the LLM parser can classify required, preferred, and ambiguous content more accurately.

### Playwright

Best for JavaScript-rendered pages and pages where visible content matters.

Pros:

- Sees the page more like a user.
- Can extract rendered headings and grouped visible text.
- Works where HTTP-only extraction fails.

Cons:

- Slower.
- Requires browser binaries.
- More complex in containers and CI.
- Still may fail on anti-bot protections.

### Manual Paste

Still valuable for blocked pages. The app preserves the source URL so manual input can still be tracked.

## Learned Selector Observations

CareerPilot stores local selector observations under ignored `data/`.

```text
data/career_page_selectors.local.json
```

The selector-learning layer stores declarative content-root selectors, not executable code.

```text
candidate selector
  -> structural validation
  -> optional semantic validation
  -> promoted selector after repeated success
  -> rediscovery if the page drifts
```

This reduces token usage and page noise without letting the system write or execute scraper code.

## Reviewed Extraction Overrides

Some domains may have committed reviewed defaults under `app/extraction_overrides/`.

Reviewed overrides are human-readable, typed, and reviewable in Git. They are useful for important target companies, but the project should not require a committed override for every site.

## Future Target-Company Discovery

Broad internet search is deferred. The more useful production path is a curated watchlist:

```text
target company config
  -> source connector
  -> normalized postings
  -> dedupe
  -> semantic relevance filter
  -> user review
  -> optional tracker save
```

Connector strategy:

- Use official APIs or feeds when available.
- Use common ATS connectors where practical.
- Use browser extraction for JavaScript-heavy career pages.
- Use manual review for uncertain results.

Cron or scheduled scans should come after manual scans are reliable.

## Safety Boundaries

- Do not execute generated Python or JavaScript from the model.
- Store learned selectors as data, not code.
- Validate selector output before promotion.
- Keep user-controlled fallback paths.
- Respect local privacy boundaries and ignored profile/application data.

## Interview Framing

> I treated job ingestion as a layered reliability problem. Plain HTTP is cheap and testable, JSON-LD gives canonical metadata, Playwright handles rendered pages, and selector learning reduces repeated noise. I avoided autonomous scraper-code generation; the system learns declarative selectors and validates them before reuse.
