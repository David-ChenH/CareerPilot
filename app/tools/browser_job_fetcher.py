from urllib.parse import urlparse

from pydantic import BaseModel

from app.extraction_overrides.career_pages import CareerPageExtractionOverrideRegistry
from app.tools.content_root_strategy import (
    MIN_READABLE_TEXT_LENGTH,
    ContentRootStrategy,
    ContentRootStrategySource,
    ContentRootSemanticValidation,
    ContentRootValidationEvidence,
    validate_content_root,
)
from app.tools.learned_selector_store import LearnedSelectorStore
from app.tools.job_extraction import ExtractedJobPosting, sections_from_lines
from app.tools.llm_content_root_validator import (
    LLMContentRootValidatorUnavailable,
    validate_content_root_with_llm,
)


BROWSER_TIMEOUT_MS = 20_000
CONTENT_SELECTORS = [
    "main",
    "[role='main']",
    "article",
    "[class*='job-description']",
    "[class*='jobDescription']",
    "[class*='description']",
    "[data-automation-id*='jobPosting']",
    "[data-automation-id*='jobDescription']",
    "body",
]


class BrowserFetchedJobPage(BaseModel):
    url: str
    title: str | None = None
    text: str
    extraction_source: str = "browser_rendered"
    needs_browser_render: bool = False
    extracted_posting: ExtractedJobPosting | None = None
    extraction_recipe: dict | None = None
    extraction_strategy: ContentRootStrategy | None = None


class BrowserJobPageFetchError(RuntimeError):
    pass


def fetch_job_page_with_browser(
    url: str,
    selector_store: LearnedSelectorStore | None = None,
    override_registry: CareerPageExtractionOverrideRegistry | None = None,
) -> BrowserFetchedJobPage:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise BrowserJobPageFetchError("URL must start with http:// or https://.")

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise BrowserJobPageFetchError(
            "Browser fetch requires Playwright. Install it with "
            '`pip install -e ".[dev,browser]"` and `playwright install chromium`.'
        ) from error

    try:
        selector_store = selector_store or LearnedSelectorStore()
        override_registry = override_registry or CareerPageExtractionOverrideRegistry()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
                page.wait_for_load_state("networkidle", timeout=BROWSER_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                # Some career pages keep long-polling or analytics requests open.
                # We can still try to read whatever is visible after DOM content loads.
                pass

            title = page.title() or None
            strategy, text, headings = _extract_job_content(page, url, selector_store, override_registry)
            current_observation = selector_store.get(url)
            strategy = _maybe_validate_semantically(strategy, text, headings, current_observation)
            observation = selector_store.record_success(strategy)
            browser.close()
    except PlaywrightError as error:
        message = str(error)
        if "Executable doesn't exist" in message or "playwright install" in message:
            raise BrowserJobPageFetchError(
                "Playwright is installed, but Chromium is missing. Run `playwright install chromium`."
            ) from error
        if "Permission denied" in message or "bootstrap_check_in" in message:
            raise BrowserJobPageFetchError(
                "Chromium could not launch because macOS denied the browser process. "
                "Try running the app from your normal Terminal, or use manual paste for this page."
            ) from error
        raise BrowserJobPageFetchError(f"Browser fetch failed: {message}") from error

    if len(text) < MIN_READABLE_TEXT_LENGTH:
        raise BrowserJobPageFetchError(
            "Browser fetch did not find enough visible job text. "
            "The site may block automation or require login; paste the description manually."
        )

    return BrowserFetchedJobPage(
        url=url,
        title=title,
        text=text,
        extracted_posting=ExtractedJobPosting(
            metadata={"title": title, "canonical_url": url},
            sections=sections_from_lines(text, source="browser_rendered", headings=headings),
            extraction_source="browser_rendered",
            warnings=[
                f"Content-root strategy: {strategy.source.value} selector {strategy.content_selector!r}; "
                f"learned observation is {observation.status}."
            ],
        ),
        extraction_recipe=observation.model_dump(mode="json"),
        extraction_strategy=strategy,
    )


def _extract_job_content(
    page,
    url: str,
    selector_store: LearnedSelectorStore,
    override_registry: CareerPageExtractionOverrideRegistry,
) -> tuple[ContentRootStrategy, str, list[str]]:
    domain = urlparse(url).netloc.lower()
    promoted_selector = selector_store.get_promoted(url)
    if promoted_selector:
        result = _extract_selector(page, promoted_selector.content_selector, promoted_selector.heading_selector)
        if result and result[2].passed:
            return (
                ContentRootStrategy(
                    domain=domain,
                    content_selector=promoted_selector.content_selector,
                    heading_selector=promoted_selector.heading_selector,
                    source=ContentRootStrategySource.LEARNED_OBSERVATION,
                    validation=result[2],
                ),
                result[0],
                result[1],
            )
        selector_store.record_failure(url, promoted_selector.content_selector)

    override = override_registry.find_for_url(url)
    if override:
        result = _extract_selector(page, override.content_selector, override.heading_selector)
        if result and _override_passed(result[0], result[2], override.quality_checks):
            return (
                ContentRootStrategy(
                    domain=domain,
                    content_selector=override.content_selector,
                    heading_selector=override.heading_selector,
                    source=ContentRootStrategySource.REVIEWED_OVERRIDE,
                    validation=result[2],
                ),
                result[0],
                result[1],
            )

    candidates = []
    for selector in CONTENT_SELECTORS:
        result = _extract_selector(page, selector, "h1, h2, h3, h4, h5, h6")
        if result and result[2].passed:
            candidates.append((selector, *result))
    if not candidates:
        raise BrowserJobPageFetchError("Browser fetch could not find a readable content root.")
    selector, text, headings, validation = max(candidates, key=lambda candidate: candidate[3].structural_score)
    return (
        ContentRootStrategy(
            domain=domain,
            content_selector=selector,
            source=ContentRootStrategySource.BOUNDED_DISCOVERY,
            validation=validation,
        ),
        text,
        headings,
    )


def _extract_selector(
    page,
    selector: str,
    heading_selector: str,
) -> tuple[str, list[str], ContentRootValidationEvidence] | None:
    locator = page.locator(selector)
    try:
        count = min(locator.count(), 20)
    except Exception:
        return None

    best = None
    for index in range(count):
        node = locator.nth(index)
        try:
            text = node.inner_text(timeout=BROWSER_TIMEOUT_MS).strip()
            headings = node.locator(heading_selector).all_inner_texts()
        except Exception:
            continue
        validation = validate_content_root(text)
        if best is None or validation.structural_score > best[2].structural_score:
            best = (text, headings, validation)
    return best


def _score_content_candidate(text: str) -> int:
    return validate_content_root(text).structural_score


def _maybe_validate_semantically(
    strategy: ContentRootStrategy,
    text: str,
    headings: list[str],
    current_observation,
) -> ContentRootStrategy:
    if not _semantic_validation_required(strategy, current_observation):
        return strategy.model_copy(
            update={"semantic_validation": ContentRootSemanticValidation(required=False, attempted=False)}
        )

    try:
        semantic_validation = validate_content_root_with_llm(strategy=strategy, text=text, headings=headings)
    except LLMContentRootValidatorUnavailable as error:
        semantic_validation = ContentRootSemanticValidation(
            required=True,
            attempted=False,
            error=str(error),
        )
    return strategy.model_copy(update={"semantic_validation": semantic_validation})


def _semantic_validation_required(strategy: ContentRootStrategy, current_observation) -> bool:
    if current_observation is None:
        return True
    if current_observation.content_selector != strategy.content_selector:
        return True
    if current_observation.status != "promoted" and current_observation.successful_extractions + 1 >= 2:
        return True
    if current_observation.failed_extractions > 0:
        return True
    return False


def _override_passed(text: str, validation: ContentRootValidationEvidence, quality_checks) -> bool:
    if not validation.passed:
        return False
    if not quality_checks.min_characters <= validation.text_length <= quality_checks.max_characters:
        return False
    lowered = text.lower()
    if any(signal.lower() not in lowered for signal in quality_checks.expected_signals):
        return False
    if any(signal.lower() in lowered for signal in quality_checks.excluded_signals):
        return False
    return True
