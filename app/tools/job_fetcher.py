import json
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel

from app.tools.job_extraction import ExtractedJobPosting, sections_from_lines


MAX_PAGE_BYTES = 1_500_000
REQUEST_TIMEOUT_SECONDS = 12


class FetchedJobPage(BaseModel):
    url: str
    title: str | None = None
    text: str
    extraction_source: str = "readable_html"
    needs_browser_render: bool = False
    extracted_posting: ExtractedJobPosting | None = None


class JobPageFetchError(RuntimeError):
    pass


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self._in_title = False
        self._ignored_depth = 0
        self._in_job_json_ld = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._job_json_ld_parts: list[str] = []
        self._job_posting: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and attributes.get("type", "").lower() == "application/ld+json":
            self._in_job_json_ld = True
            self._job_json_ld_parts = []
        elif tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_job_json_ld:
            self._in_job_json_ld = False
            self._parse_job_json_ld()
        elif tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag == "title":
            self._in_title = False
            title = " ".join(part.strip() for part in self._title_parts if part.strip())
            self.title = title or None

    def handle_data(self, data: str) -> None:
        if self._in_job_json_ld:
            self._job_json_ld_parts.append(data)
            return
        if self._ignored_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        elif data.strip():
            self._text_parts.append(data.strip())

    @property
    def readable_text(self) -> str:
        return "\n".join(self._text_parts)

    @property
    def job_posting_text(self) -> str | None:
        if not self._job_posting:
            return None
        posting = self._job_posting
        values = [
            posting.get("title"),
            _organization_name(posting.get("hiringOrganization")),
            _location_text(posting.get("jobLocation")),
            _structured_description_text(posting.get("description")),
        ]
        text = "\n".join(str(value).strip() for value in values if value and str(value).strip())
        return text or None

    @property
    def job_posting_title(self) -> str | None:
        if not self._job_posting:
            return None
        title = self._job_posting.get("title")
        return str(title).strip() if title else None

    @property
    def job_posting_metadata(self) -> dict[str, str | None]:
        if not self._job_posting:
            return {}
        posting = self._job_posting
        return {
            "title": _clean_text(posting.get("title")),
            "company": _organization_name(posting.get("hiringOrganization")),
            "location": _location_text(posting.get("jobLocation")),
            "canonical_url": _clean_text(posting.get("url")),
            "date_posted": _clean_text(posting.get("datePosted")),
            "valid_through": _clean_text(posting.get("validThrough")),
            "employment_type": _clean_text(posting.get("employmentType")),
        }

    @property
    def job_posting_sections(self):
        if not self._job_posting:
            return []
        description = _structured_description_text(self._job_posting.get("description"))
        return sections_from_lines(description or "", source="json_ld")

    @property
    def job_posting_needs_browser_render(self) -> bool:
        if not self._job_posting:
            return False
        return _structured_description_may_be_lossy(self._job_posting.get("description"))

    def _parse_job_json_ld(self) -> None:
        raw_json = "".join(self._job_json_ld_parts).strip()
        if not raw_json:
            return
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                self._job_posting = candidate
                return


def fetch_job_page(url: str) -> FetchedJobPage:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise JobPageFetchError("URL must start with http:// or https://.")

    request = Request(
        url,
        headers={
            "User-Agent": "JobSearchAgent/0.1 (+https://github.com/)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                raise JobPageFetchError(f"Unsupported content type: {content_type or 'unknown'}.")
            raw_body = response.read(MAX_PAGE_BYTES)
    except HTTPError as error:
        if error.code in {401, 403, 429}:
            raise JobPageFetchError(
                f"Job page blocked automated fetching with HTTP {error.code}. "
                "Open the link in your browser and paste the job description manually."
            ) from error
        raise JobPageFetchError(f"Job page returned HTTP {error.code}.") from error
    except URLError as error:
        raise JobPageFetchError(
            f"Could not fetch job page: {error.reason}. "
            "Check your network connection, or paste the job description manually."
        ) from error
    except TimeoutError as error:
        raise JobPageFetchError("Timed out while fetching job page.") from error

    html = raw_body.decode("utf-8", errors="replace")
    parser = _ReadableHTMLParser()
    parser.feed(html)
    text = (parser.job_posting_text or parser.readable_text).strip()
    if len(text) < 200:
        raise JobPageFetchError(
            "Fetched page did not contain enough readable job text. "
            "The site may render the job description with JavaScript; paste the description manually for now."
        )

    extraction_source = "json_ld" if parser.job_posting_text else "readable_html"
    return FetchedJobPage(
        url=url,
        title=parser.job_posting_title or parser.title,
        text=text,
        extraction_source=extraction_source,
        needs_browser_render=parser.job_posting_needs_browser_render,
        extracted_posting=ExtractedJobPosting(
            metadata=parser.job_posting_metadata,
            sections=parser.job_posting_sections or sections_from_lines(text, source=extraction_source),
            extraction_source=extraction_source,
            warnings=["Structured JobPosting description may have lost section boundaries."]
            if parser.job_posting_needs_browser_render
            else [],
        ),
    )


class _StructuredDescriptionParser(HTMLParser):
    BLOCK_TAGS = {"br", "div", "h1", "h2", "h3", "h4", "li", "ol", "p", "section", "ul"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    @property
    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line).strip()


def _structured_description_text(value) -> str | None:
    if not value:
        return None
    parser = _StructuredDescriptionParser()
    parser.feed(str(value))
    return parser.text or None


def _structured_description_may_be_lossy(value) -> bool:
    description = _structured_description_text(value)
    if not description or description.count("\n") >= 3:
        return False
    lowered = description.lower()
    structural_signals = [
        "qualification",
        "responsibilit",
        "bachelor",
        "master",
        "preferred",
        "required",
        "minimum",
    ]
    return len(description) >= 600 and sum(signal in lowered for signal in structural_signals) >= 2


def _organization_name(value) -> str | None:
    if isinstance(value, dict):
        name = value.get("name")
        return str(name).strip() if name else None
    return str(value).strip() if value else None


def _clean_text(value) -> str | None:
    return str(value).strip() if value else None


def _location_text(value) -> str | None:
    if not isinstance(value, dict):
        return str(value).strip() if value else None
    address = value.get("address")
    if not isinstance(address, dict):
        return None
    parts = []
    for key in ["addressLocality", "addressRegion", "addressCountry"]:
        part = address.get(key)
        if isinstance(part, dict):
            part = part.get("name")
        if part:
            parts.append(str(part).strip())
    return ", ".join(parts) or None
