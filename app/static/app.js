const form = document.querySelector("#analysis-form");
const urlInput = document.querySelector("#job-url");
const descriptionInput = document.querySelector("#job-description");
const saveInput = document.querySelector("#save-job");
const resultPanel = document.querySelector("#analysis-result");
const statusPanel = document.querySelector("#analysis-status");
const errorPanel = document.querySelector("#analysis-error");
const jobsList = document.querySelector("#jobs-list");
const jobDetailPanel = document.querySelector("#job-detail");
const refreshButton = document.querySelector("#refresh-jobs");
const fetchUrlButton = document.querySelector("#fetch-url");

const statuses = ["discovered", "interested", "applied", "interviewing", "rejected", "offer"];
let selectedJobId = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  clearStatus();
  resultPanel.hidden = true;

  const description = descriptionInput.value.trim();
  if (!description) {
    showError("Paste a job description before analyzing.");
    return;
  }

  try {
    showStatus("Analyzing pasted job description...");
    const response = await fetch("/jobs/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        save: saveInput.checked,
        source_url: urlInput.value.trim() || null,
        use_llm: true,
        use_llm_guidance: true,
      }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const analysis = await response.json();
    renderAnalysis(analysis);
    await loadJobs();
    showStatus("Analysis complete.");
  } catch (error) {
    showError(`Analysis failed: ${error.message}`);
  } finally {
    setTimeout(clearStatus, 1800);
  }
});

refreshButton.addEventListener("click", loadJobs);
fetchUrlButton.addEventListener("click", fetchFromUrl);

async function fetchFromUrl() {
  clearError();
  clearStatus();
  resultPanel.hidden = true;

  const url = urlInput.value.trim();
  if (!url) {
    showError("Paste a job link before fetching.");
    return;
  }

  try {
    fetchUrlButton.disabled = true;
    fetchUrlButton.textContent = "Fetching...";
    showStatus("Fetching job page. If plain fetch fails, the backend may try browser rendering.");
    const response = await fetch("/jobs/fetch-and-analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        save: saveInput.checked,
        use_browser_fallback: true,
        use_llm: true,
        use_llm_guidance: true,
      }),
    });
    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }
    const analysis = await response.json();
    descriptionInput.value = analysis.parsed_job.description;
    renderAnalysis(analysis);
    await loadJobs();
    showStatus("Fetched and analyzed job link.");
  } catch (error) {
    showError(`Fetch failed: ${error.message}`);
  } finally {
    fetchUrlButton.disabled = false;
    fetchUrlButton.textContent = "Fetch link";
    setTimeout(clearStatus, 1800);
  }
}

function renderAnalysis(analysis) {
  const job = analysis.parsed_job;
  const fit = analysis.fit;

  resultPanel.innerHTML = `
    <div class="score-row">
      <div class="score">${fit.score}</div>
      <div>
        <h3>${escapeHtml(job.title || "Untitled job")}</h3>
        <span class="priority">${escapeHtml(fit.priority)} priority</span>
        <p class="parser-note">${escapeHtml(parserLabel(analysis))}</p>
        <p class="parser-note">${escapeHtml(scorerLabel(analysis))}</p>
        <p class="parser-note">${escapeHtml(guidanceLabel(analysis))}</p>
        ${renderBaselineNote(analysis)}
      </div>
    </div>
    <p>${escapeHtml(fit.summary)}</p>
    <div class="result-grid">
      ${renderList("Strong matches", fit.strong_matches)}
      ${renderList("Skill gaps", fit.gaps)}
      ${renderList("Growth areas", fit.growth_areas)}
      ${renderList("Concerns", fit.concerns)}
      ${renderList("Apply reasoning", analysis.guidance?.apply_reasoning)}
      ${renderList("Prep plan", analysis.guidance?.prep_plan || analysis.prep_topics)}
      ${renderList("Resume guidance", analysis.guidance?.resume_guidance || analysis.resume_emphasis)}
      ${renderList("Learning plan", analysis.guidance?.learning_plan)}
      ${renderList("Interview focus", analysis.guidance?.interview_focus)}
      ${renderList("Detected skills", job.skills)}
      ${renderList("Required skills", job.required_skills)}
      ${renderList("Preferred skills", job.preferred_skills)}
      ${renderList("Qualifications to validate", job.ambiguous_qualifications)}
      ${renderList("Transition notes", fit.transition_notes)}
      ${renderList("Responsibilities", job.responsibilities)}
      ${renderList("Requirements", job.requirements)}
    </div>
  `;
  resultPanel.hidden = false;
}

async function loadJobs() {
  clearError();
  try {
    const response = await fetch("/jobs");
    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }
    const jobs = await response.json();
    renderJobs(jobs);
  } catch (error) {
    showError(`Could not load jobs: ${error.message}`);
  }
}

function renderJobs(jobs) {
  if (!jobs.length) {
    jobsList.innerHTML = `<div class="empty-state">No saved jobs yet.</div>`;
    return;
  }

  jobsList.innerHTML = jobs.map((job) => `
    <article class="job-card ${job.id === selectedJobId ? "selected" : ""}" data-view-job-id="${job.id}">
      <div class="job-card-header">
        <div>
          <p class="job-title">${escapeHtml(job.title || "Untitled job")}</p>
          <p class="job-meta">
            ${escapeHtml(job.company || "Unknown company")}
            ${job.location ? ` · ${escapeHtml(job.location)}` : ""}
          </p>
          <p class="job-summary">${escapeHtml(summarizeJob(job.description))}</p>
        </div>
        <span class="priority">${job.fit_score} · ${escapeHtml(job.priority)}</span>
      </div>
      <label for="status-${job.id}">Status</label>
      <select id="status-${job.id}" data-job-id="${job.id}">
        ${statuses.map((status) => `
          <option value="${status}" ${status === job.status ? "selected" : ""}>${status}</option>
        `).join("")}
      </select>
      <div class="job-actions">
        ${job.source_url ? `<a class="source-link" href="${escapeHtml(job.source_url)}" target="_blank" rel="noreferrer">Open link</a>` : "<span></span>"}
        <button class="danger-button" type="button" data-delete-job-id="${job.id}">Delete</button>
      </div>
    </article>
  `).join("");

  jobsList.querySelectorAll("[data-view-job-id]").forEach((card) => {
    card.addEventListener("click", async (event) => {
      if (event.target.closest("select") || event.target.closest("button") || event.target.closest("a")) {
        return;
      }
      selectedJobId = Number(event.currentTarget.dataset.viewJobId);
      await loadJobDetail(selectedJobId);
      renderJobs(jobs);
    });
  });

  jobsList.querySelectorAll("select").forEach((select) => {
    select.addEventListener("change", async (event) => {
      const jobId = event.target.dataset.jobId;
      const status = event.target.value;
      await updateStatus(jobId, status);
    });
  });

  jobsList.querySelectorAll("[data-delete-job-id]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      const jobId = event.target.dataset.deleteJobId;
      await deleteJob(jobId);
    });
  });
}

async function loadJobDetail(jobId) {
  clearError();
  try {
    const response = await fetch(`/jobs/${jobId}`);
    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }
    const detail = await response.json();
    renderJobDetail(detail);
  } catch (error) {
    showError(`Could not load job detail: ${error.message}`);
  }
}

function renderJobDetail(detail) {
  const job = detail.job;
  const analysis = detail.analysis;
  const fit = analysis?.fit;
  const guidance = analysis?.guidance;

  jobDetailPanel.innerHTML = `
    <div class="job-detail-header">
      <div>
        <h3>${escapeHtml(job.title || "Untitled job")}</h3>
        <p class="job-meta">
          ${escapeHtml(job.company || "Unknown company")}
          ${job.location ? ` · ${escapeHtml(job.location)}` : ""}
        </p>
      </div>
      <span class="priority">${escapeHtml(job.fit_score)} · ${escapeHtml(job.priority)}</span>
    </div>
    ${job.source_url ? `<p><a class="source-link" href="${escapeHtml(job.source_url)}" target="_blank" rel="noreferrer">Open original job link</a></p>` : ""}
    ${analysis ? renderSavedAnalysis(fit, guidance, analysis.parsed_job) : `<p class="empty-state">No saved analysis payload for this older job. Re-analyze the job to save full details.</p>`}
  `;
  jobDetailPanel.hidden = false;
}

function renderSavedAnalysis(fit, guidance, parsedJob) {
  return `
    <p>${escapeHtml(fit?.summary || "No summary saved.")}</p>
    <div class="detail-grid">
      ${renderList("Apply reasoning", guidance?.apply_reasoning)}
      ${renderList("Prep plan", guidance?.prep_plan)}
      ${renderList("Resume guidance", guidance?.resume_guidance)}
      ${renderList("Learning plan", guidance?.learning_plan)}
      ${renderList("Interview focus", guidance?.interview_focus)}
      ${renderList("Skill gaps", fit?.gaps)}
      ${renderList("Growth areas", fit?.growth_areas)}
      ${renderList("Required skills", parsedJob?.required_skills)}
      ${renderList("Qualifications to validate", parsedJob?.ambiguous_qualifications)}
    </div>
  `;
}

async function updateStatus(jobId, status) {
  clearError();
  try {
    const response = await fetch(`/jobs/${jobId}/status?status=${encodeURIComponent(status)}`, {
      method: "PATCH",
    });
    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }
    await loadJobs();
  } catch (error) {
    showError(`Could not update status: ${error.message}`);
  }
}

async function deleteJob(jobId) {
  clearError();
  try {
    const response = await fetch(`/jobs/${jobId}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }
    await loadJobs();
  } catch (error) {
    showError(`Could not delete job: ${error.message}`);
  }
}

function renderList(title, items) {
  const values = items && items.length ? items : ["None detected yet"];
  return `
    <section>
      <h3>${escapeHtml(title)}</h3>
      <ul>
        ${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>
  `;
}

function parserLabel(analysis) {
  if (analysis.parser_used === "llm") {
    return "Parsed with LLM structured extraction";
  }
  if (analysis.parser_warning) {
    return `Parsed with deterministic fallback: ${analysis.parser_warning}`;
  }
  return "Parsed with deterministic rules";
}

function scorerLabel(analysis) {
  return "Primary score from LLM semantic evaluator";
}

function guidanceLabel(analysis) {
  if (analysis.guidance_used === "llm") {
    return "Guidance generated with LLM application coach";
  }
  if (analysis.guidance_warning) {
    return `Application guidance unavailable: ${analysis.guidance_warning}`;
  }
  return "Application guidance was not requested";
}

function renderBaselineNote() {
  return "";
}

function summarizeJob(description) {
  const normalized = String(description || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) {
    return "No description saved yet.";
  }
  const withoutLikelyTitle = normalized
    .split(/(?<=[.!?])\s+/)
    .find((sentence) => sentence.length > 80) || normalized;
  return truncate(withoutLikelyTitle, 180);
}

function truncate(value, maxLength) {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1).trim()}…`;
}

async function getErrorMessage(response) {
  const contentType = response.headers.get("Content-Type") || "";
  if (contentType.includes("application/json")) {
    const data = await response.json();
    return data.detail || JSON.stringify(data);
  }
  return response.text();
}

function showStatus(message) {
  statusPanel.textContent = message;
  statusPanel.hidden = false;
}

function clearStatus() {
  statusPanel.textContent = "";
  statusPanel.hidden = true;
}

function showError(message) {
  errorPanel.textContent = message;
  errorPanel.hidden = false;
}

function clearError() {
  errorPanel.textContent = "";
  errorPanel.hidden = true;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadJobs();
