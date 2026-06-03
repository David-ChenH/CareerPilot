# Job Fetching Tradeoffs

This app supports analyzing jobs from pasted descriptions and simple job links. A real job-search agent eventually needs stronger ingestion because many career pages do not expose the full job description as plain HTML.

## The problem

When a user pastes a job link, the app needs to turn the URL into useful text:

```text
job URL -> job description text -> parser -> scorer -> tracker
```

That sounds simple, but job pages vary a lot:

- Some pages return readable HTML.
- Some render the description with JavaScript.
- Some call internal APIs after the page loads.
- Some block automated requests.
- Some require cookies, region settings, or login.
- Some have anti-bot protections.

The Meta Careers example is a good case: a plain server-side HTTP fetch reaches the page, but it does not return enough readable job text for analysis.

Structured data also has quality levels. A schema.org `JobPosting` JSON-LD block may expose canonical title, company, location, and description while flattening headings such as `Required Qualifications` and `Preferred Qualifications` into one paragraph. For individual URL analysis, CareerPilot combines JSON-LD metadata with rendered sections by default. HTTP-only extraction remains available for a future low-cost bulk-discovery pass.

## Option 1: Plain HTTP fetch

Current implementation:

```text
urllib request -> HTML parser -> readable text
```

Code:

```text
app/tools/job_fetcher.py
```

Pros:

- Simple to build.
- Fast and lightweight.
- Easy to test.
- Does not require a browser runtime.
- Lower operational complexity.
- Good for static company pages, simple blogs, and plain HTML job posts.

Cons:

- Fails when content is rendered by JavaScript.
- Fails when sites block non-browser requests.
- Cannot interact with pages.
- Cannot use logged-in browser state.
- Extracted text can include navigation, footer, or unrelated page text.

Best use:

- First-pass ingestion.
- Pages with server-rendered job descriptions.
- Local MVP where reliability is less important than simplicity.

Current individual-analysis rule:

```text
HTTP fetch -> canonical JSON-LD metadata
Playwright -> visible headings and grouped text
learned selector store -> reuse a validated domain-specific content root when available
merge -> typed ExtractedJobPosting artifact
LLM -> semantic section classification
fallback -> keep HTTP extraction if rendering is unavailable
```

## Option 2: Browser automation with Playwright

Current optional fallback implementation:

```text
Playwright opens URL -> waits for rendering -> extracts visible page text -> parser -> scorer
```

Code:

```text
app/tools/browser_job_fetcher.py
```

Pros:

- Handles JavaScript-rendered pages.
- Extracts what a real user can see.
- Can click tabs, expand sections, or wait for page content.
- Can support company career pages that plain HTTP cannot.
- Useful demo of real agent tool usage.

Cons:

- More complex infrastructure.
- Slower than plain HTTP.
- Requires browser binaries and runtime setup.
- Can be flaky if page structure or timing changes.
- Harder to run in containers and CI.
- May still fail on anti-bot protections.
- Raises more safety/privacy concerns if using logged-in browser state.
- Requires users to install the browser extra and Chromium:

```bash
pip install -e ".[dev,browser]"
playwright install chromium
```

Best use:

- Company career pages with JavaScript-rendered descriptions.
- Agentic workflows where the system needs to inspect, click, and adapt.
- Portfolio demonstration of tool use and browser-based agents.

## Option 3: Official APIs or partner feeds

Possible implementation:

```text
job board API -> normalized job data -> parser/scorer -> tracker
```

Pros:

- Most reliable when available.
- Structured data.
- Lower scraping risk.
- Easier to paginate, filter, and deduplicate.
- Better for production systems.

Cons:

- Many job boards do not provide public APIs.
- APIs may be paid, rate-limited, or restricted.
- Coverage can be incomplete.
- Still need normalization across providers.

Best use:

- Production-grade ingestion.
- Job boards or aggregators with supported APIs.
- Systems where compliance and reliability matter more than coverage.

## Option 4: User-assisted paste

Current fallback:

```text
user opens page -> copies description -> pastes text -> app analyzes and saves source URL
```

Pros:

- Reliable for almost every job page the user can view.
- Avoids scraping and anti-bot complexity.
- Keeps the MVP useful immediately.
- Preserves the original source URL in the tracker.

Cons:

- Manual step.
- Less automated.
- Not enough for scheduled job discovery.

Best use:

- MVP fallback.
- Blocked or JavaScript-heavy pages.
- Cases where the user wants full control over what text is analyzed.

## Recommended roadmap

The app should use a layered ingestion strategy:

```text
1. Try plain HTTP fetch.
2. If readable text is too short, try Playwright browser fetch.
3. If browser fetch fails, show a clear fallback message.
4. Let the user paste manually while preserving the source URL.
5. Add official APIs/search providers for broader discovery.
```

This layered approach is better than jumping straight to browser automation because it keeps the first version simple, testable, and reliable while leaving room for more capable ingestion.

## Interview explanation

A strong interview framing:

> I started with plain HTTP fetch because it is fast, simple, and easy to test. It works for static job pages and keeps the MVP small. When I tested real career pages, I found that some pages, such as large company career portals, render job details with JavaScript or block non-browser requests. I added Playwright as a browser-rendered fallback while still keeping plain HTTP as the cheap first-pass strategy. If both fail, the app preserves the source URL and lets the user paste the description manually.

This shows practical engineering judgment:

- Start simple.
- Measure where it fails.
- Add complexity only where it solves a real failure mode.
- Keep fallback paths usable.
- Document tradeoffs instead of pretending one approach works everywhere.
