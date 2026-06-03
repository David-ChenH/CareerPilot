# Self-Evolving Career-Page Extraction

CareerPilot should learn how to extract a job posting from a careers domain without autonomously rewriting executable scraper code.

## Problem

Sending an entire rendered careers page to an LLM on every visit is expensive and noisy. Large pages can include navigation, related jobs, legal text, and application UI. The model should analyze the posting, not rediscover the page layout every time.

## Design Boundary

The learning layer stores declarative learned selector observations:

```json
{
  "domain": "careers.example.com",
  "content_selector": "main",
  "heading_selector": "h1, h2, h3, h4, h5, h6",
  "status": "promoted",
  "successful_extractions": 3,
  "failed_extractions": 0,
  "last_score": 12
}
```

It does not save or execute LLM-generated Python or JavaScript. Website content is untrusted input, so allowing a page to teach the application executable code would create a security boundary violation.

## Learning Loop

```text
open careers page
  -> try promoted learned selector for its domain
  -> validate extracted text with deterministic quality signals
  -> use the selector when confidence is sufficient
  -> otherwise inspect a bounded set of safe CSS selectors
  -> select the highest-quality content root
  -> record a successful observation
  -> promote the selector after repeated success
  -> return it to candidate state if a later fetch fails validation
```

The initial implementation stores local observations in:

```text
data/career_page_selectors.local.json
```

The `data/` directory is ignored by Git.

## Token Savings

The selector layer narrows rendered HTML before the LLM parser sees it. This reduces noisy context and improves extraction quality. It does not eliminate semantic analysis tokens: a new or changed job description still needs parsing and scoring.

Semantic validation is intentionally gated. Deterministic structural validation runs first on every candidate. The LLM validator is attempted only when a selector is new, about to be promoted, or replacing a stale selector. If semantic validation is required but unavailable or failed, the selector can remain a candidate but is not promoted.

A later cache layer should reuse a previous LLM analysis when the normalized posting content hash and analysis workflow version are unchanged.

## Future Improvements

1. Add ambiguous-candidate comparison when two content roots have similar structural scores.
2. Persist selector observation history instead of only the current projection.
3. Show learned selectors and confidence in Settings.
4. Add user review for selector promotion on sensitive or low-confidence domains.
5. Add ATS-level extraction profiles for Greenhouse, Lever, Ashby, Workday, and selected large-company portals.
6. Cache LLM extraction and scoring by content hash, prompt version, model, and profile version.
7. Add offline eval fixtures for each promoted selector to catch page drift.

## Interview Explanation

> I separated adaptation from code execution. The agent learns a declarative content-root selector per careers domain, validates it with deterministic quality signals, and promotes it only after repeated success. If the page structure changes, the selector falls back to discovery. This reduces token usage while keeping the learning loop inspectable and safe. Semantic analysis remains LLM-led, and the next optimization is version-aware analysis caching.
