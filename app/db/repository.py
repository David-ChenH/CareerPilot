import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.db.analysis_migrations import CURRENT_ANALYSIS_SCHEMA_VERSION, migrate_analysis_payload
from app.db.models import (
    AgentTask,
    AgentTaskStatus,
    AgentTaskStep,
    AgentTaskType,
    ApplicationStatus,
    ApplicationType,
    ChatRole,
    GlobalChatMessage,
    GlobalChatSession,
    JobChatMessage,
    JobDetail,
    JobRecord,
    LeetCodeProblem,
    LeetCodeStatus,
    PrepPlan,
    ProfileProposal,
    ResumeVersion,
)


DEFAULT_DB_PATH = Path("data/jobs.sqlite3")
JOB_SELECT_COLUMNS = """
id, source_url, title, company, location, description, skills, fit_score, priority, status,
application_type, analysis_json, analysis_schema_version, analysis_provenance_json
"""


class JobRepository:
    def __init__(self, path: Path = DEFAULT_DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def save_job(self, job: JobRecord) -> JobRecord:
        job.analysis, job.analysis_schema_version = migrate_analysis_payload(
            job.analysis,
            job.analysis_schema_version or CURRENT_ANALYSIS_SCHEMA_VERSION,
        )
        with self._connect() as conn:
            existing = self._find_duplicate(conn, job)
            if existing:
                return self._refresh_existing_job(conn, existing, job)

            cursor = conn.execute(
                """
                INSERT INTO jobs (
                  source_url, title, company, location, description, skills, fit_score, priority, status,
                  application_type, analysis_json, analysis_schema_version, analysis_provenance_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.source_url,
                    job.title,
                    job.company,
                    job.location,
                    job.description,
                    json.dumps(job.skills),
                    job.fit_score,
                    job.priority,
                    job.status.value,
                    job.application_type.value,
                    json.dumps(job.analysis) if job.analysis else None,
                    job.analysis_schema_version,
                    json.dumps(job.analysis_provenance.model_dump()) if job.analysis_provenance else None,
                ),
            )
            if job.analysis:
                self._append_analysis_version(
                    conn,
                    cursor.lastrowid,
                    job.analysis,
                    job.analysis_schema_version,
                    job.analysis_provenance,
                )
            conn.commit()
            job.id = cursor.lastrowid
            return job

    def update_job_analysis(self, job_id: int, incoming: JobRecord) -> JobRecord | None:
        incoming.analysis, incoming.analysis_schema_version = migrate_analysis_payload(
            incoming.analysis,
            incoming.analysis_schema_version or CURRENT_ANALYSIS_SCHEMA_VERSION,
        )
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {JOB_SELECT_COLUMNS}
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            existing = self._row_to_job(row) if row else None
            if existing is None:
                return None
            return self._refresh_existing_job(conn, existing, incoming)

    def list_jobs(self) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {JOB_SELECT_COLUMNS}
                FROM jobs
                ORDER BY id DESC
                """
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def delete_job(self, job_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    def update_status(self, job_id: int, status: ApplicationStatus) -> JobRecord | None:
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))
            conn.commit()
            row = conn.execute(
                f"""
                SELECT {JOB_SELECT_COLUMNS}
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_chat_messages(self, job_id: int) -> list[JobChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, job_id, role, content, used_web_search, citations_json, created_at
                FROM job_chat_messages
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()
        return [self._row_to_chat_message(row) for row in rows]

    def delete_chat_messages(self, job_id: int) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM job_chat_messages WHERE job_id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount

    def add_chat_message(self, message: JobChatMessage) -> JobChatMessage:
        created_at = message.created_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_chat_messages (job_id, role, content, used_web_search, citations_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.job_id,
                    message.role.value,
                    message.content,
                    1 if message.used_web_search else 0,
                    json.dumps(message.citations),
                    created_at,
                ),
            )
            conn.commit()
        return JobChatMessage(
            id=cursor.lastrowid,
            job_id=message.job_id,
            role=message.role,
            content=message.content,
            used_web_search=message.used_web_search,
            citations=message.citations,
            created_at=created_at,
        )

    def list_global_chat_sessions(self) -> list[GlobalChatSession]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM global_chat_sessions
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        return [self._row_to_global_chat_session(row) for row in rows]

    def get_global_chat_session(self, session_id: int) -> GlobalChatSession | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM global_chat_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        return self._row_to_global_chat_session(row) if row else None

    def create_global_chat_session(self, title: str = "New chat") -> GlobalChatSession:
        now = datetime.now(timezone.utc).isoformat()
        clean_title = title.strip()[:80] or "New chat"
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO global_chat_sessions (title, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (clean_title, now, now),
            )
            conn.commit()
        return GlobalChatSession(id=cursor.lastrowid, title=clean_title, created_at=now, updated_at=now)

    def delete_global_chat_session(self, session_id: int) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM global_chat_messages WHERE session_id = ?", (session_id,))
            cursor = conn.execute("DELETE FROM global_chat_sessions WHERE id = ?", (session_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_global_chat_messages(self, session_id: int | None = None) -> list[GlobalChatMessage]:
        session = self._resolve_global_chat_session(session_id)
        if session.id is None:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, used_web_search, citations_json, created_at
                FROM global_chat_messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session.id,),
            ).fetchall()
        return [self._row_to_global_chat_message(row) for row in rows]

    def delete_global_chat_messages(self, session_id: int | None = None) -> int:
        with self._connect() as conn:
            if session_id is None:
                cursor = conn.execute("DELETE FROM global_chat_messages")
            else:
                cursor = conn.execute("DELETE FROM global_chat_messages WHERE session_id = ?", (session_id,))
            conn.commit()
            return cursor.rowcount

    def add_global_chat_message(self, message: GlobalChatMessage) -> GlobalChatMessage:
        created_at = message.created_at or datetime.now(timezone.utc).isoformat()
        session = self._resolve_global_chat_session(message.session_id, create_if_missing=True)
        if session.id is None:
            raise ValueError("Could not resolve global chat session.")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO global_chat_messages (session_id, role, content, used_web_search, citations_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    message.role.value,
                    message.content,
                    1 if message.used_web_search else 0,
                    json.dumps(message.citations),
                    created_at,
                ),
            )
            conn.execute(
                "UPDATE global_chat_sessions SET updated_at = ? WHERE id = ?",
                (created_at, session.id),
            )
            conn.commit()
        return GlobalChatMessage(
            id=cursor.lastrowid,
            session_id=session.id,
            role=message.role,
            content=message.content,
            used_web_search=message.used_web_search,
            citations=message.citations,
            created_at=created_at,
        )

    def save_prep_plan(self, plan: PrepPlan) -> PrepPlan:
        now = datetime.now(timezone.utc).isoformat()
        created_at = plan.created_at or now
        updated_at = now
        payload = plan.model_dump(exclude={"id", "created_at", "updated_at"}, mode="json")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO prep_plans (
                  title, source, timeline_days, hours_per_day, plan_json, schema_version, revision,
                  provenance_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.title,
                    plan.source,
                    plan.timeline_days,
                    plan.hours_per_day,
                    json.dumps(payload),
                    plan.schema_version,
                    plan.revision,
                    json.dumps(plan.provenance.model_dump()) if plan.provenance else None,
                    created_at,
                    updated_at,
                ),
            )
            self._append_prep_plan_version(conn, cursor.lastrowid, plan, created_at)
            conn.commit()
        return PrepPlan(
            id=cursor.lastrowid,
            title=plan.title,
            source=plan.source,
            timeline_days=plan.timeline_days,
            hours_per_day=plan.hours_per_day,
            days=plan.days,
            schema_version=plan.schema_version,
            revision=plan.revision,
            provenance=plan.provenance,
            workflow_graph=plan.workflow_graph,
            workflow_run=plan.workflow_run,
            evaluation=plan.evaluation,
            created_at=created_at,
            updated_at=updated_at,
        )

    def list_prep_plans(self) -> list[PrepPlan]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, source, timeline_days, hours_per_day, plan_json, schema_version, revision,
                       provenance_json, created_at, updated_at
                FROM prep_plans
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        return [self._row_to_prep_plan(row) for row in rows]

    def get_prep_plan(self, plan_id: int) -> PrepPlan | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, source, timeline_days, hours_per_day, plan_json, schema_version, revision,
                       provenance_json, created_at, updated_at
                FROM prep_plans
                WHERE id = ?
                """,
                (plan_id,),
            ).fetchone()
        return self._row_to_prep_plan(row) if row else None

    def update_prep_task(self, plan_id: int, day: int, task_index: int, completed: bool) -> PrepPlan | None:
        plan = self.get_prep_plan(plan_id)
        if plan is None:
            return None
        day_match = next((item for item in plan.days if item.day == day), None)
        if day_match is None or task_index < 0 or task_index >= len(day_match.tasks):
            return None
        day_match.tasks[task_index].completed = completed
        plan.revision += 1
        updated_at = datetime.now(timezone.utc).isoformat()
        payload = plan.model_dump(exclude={"id", "created_at", "updated_at"}, mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE prep_plans
                SET plan_json = ?, revision = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(payload), plan.revision, updated_at, plan_id),
            )
            self._append_prep_plan_version(conn, plan_id, plan, updated_at)
            conn.commit()
        plan.updated_at = updated_at
        return plan

    def list_leetcode_problems(self) -> list[LeetCodeProblem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, url, category, tags_json, note, status, created_at, updated_at
                FROM leetcode_problems
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        return [self._row_to_leetcode_problem(row) for row in rows]

    def create_leetcode_problem(self, problem: LeetCodeProblem) -> LeetCodeProblem:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO leetcode_problems (title, url, category, tags_json, note, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    problem.title,
                    problem.url,
                    problem.category,
                    json.dumps(problem.tags),
                    problem.note,
                    problem.status.value,
                    now,
                    now,
                ),
            )
            conn.commit()
        return problem.model_copy(update={"id": cursor.lastrowid, "created_at": now, "updated_at": now})

    def update_leetcode_problem(self, problem_id: int, incoming: LeetCodeProblem) -> LeetCodeProblem | None:
        existing = self.get_leetcode_problem(problem_id)
        if existing is None:
            return None
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE leetcode_problems
                SET title = ?, url = ?, category = ?, tags_json = ?, note = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    incoming.title,
                    incoming.url,
                    incoming.category,
                    json.dumps(incoming.tags),
                    incoming.note,
                    incoming.status.value,
                    updated_at,
                    problem_id,
                ),
            )
            conn.commit()
        return incoming.model_copy(update={"id": problem_id, "created_at": existing.created_at, "updated_at": updated_at})

    def get_leetcode_problem(self, problem_id: int) -> LeetCodeProblem | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, url, category, tags_json, note, status, created_at, updated_at
                FROM leetcode_problems
                WHERE id = ?
                """,
                (problem_id,),
            ).fetchone()
        return self._row_to_leetcode_problem(row) if row else None

    def delete_leetcode_problem(self, problem_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM leetcode_problems WHERE id = ?", (problem_id,))
            conn.commit()
        return cursor.rowcount > 0

    def create_agent_task(
        self,
        task_type: AgentTaskType,
        task_input: dict,
        task_id: str,
    ) -> AgentTask:
        now = datetime.now(timezone.utc).isoformat()
        task = AgentTask(
            id=task_id,
            type=task_type,
            status=AgentTaskStatus.QUEUED,
            input=task_input,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_tasks (id, type, status, input_json, steps_json, artifacts_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.type.value,
                    task.status.value,
                    json.dumps(task.input),
                    json.dumps([step.model_dump() for step in task.steps]),
                    json.dumps(task.artifacts),
                    task.error,
                    task.created_at,
                    task.updated_at,
                ),
            )
            conn.commit()
        return task

    def get_agent_task(self, task_id: str) -> AgentTask | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, type, status, input_json, steps_json, artifacts_json, error, created_at, updated_at
                FROM agent_tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
        return self._row_to_agent_task(row) if row else None

    def update_agent_task(
        self,
        task_id: str,
        status: AgentTaskStatus | None = None,
        artifacts: dict | None = None,
        error: str | None = None,
    ) -> AgentTask | None:
        task = self.get_agent_task(task_id)
        if task is None:
            return None
        if status is not None:
            task.status = status
        if artifacts:
            task.artifacts = {**task.artifacts, **artifacts}
        if error is not None:
            task.error = error
        task.updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_tasks
                SET status = ?, artifacts_json = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    task.status.value,
                    json.dumps(task.artifacts),
                    task.error,
                    task.updated_at,
                    task.id,
                ),
            )
            conn.commit()
        return task

    def start_agent_task_step(self, task_id: str, name: str, summary: str | None = None) -> AgentTask | None:
        task = self.get_agent_task(task_id)
        if task is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        task.steps.append(AgentTaskStep(name=name, status="running", started_at=now, summary=summary))
        task.updated_at = now
        self._write_agent_task_steps(task)
        return task

    def complete_agent_task_step(self, task_id: str, name: str, summary: str | None = None) -> AgentTask | None:
        return self._finish_agent_task_step(task_id, name, status="completed", summary=summary)

    def fail_agent_task_step(self, task_id: str, name: str, error: str) -> AgentTask | None:
        return self._finish_agent_task_step(task_id, name, status="failed", error=error)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_url TEXT,
                  title TEXT,
                  company TEXT,
                  location TEXT,
                  description TEXT NOT NULL,
                  skills TEXT NOT NULL,
                  fit_score INTEGER NOT NULL,
                  priority TEXT NOT NULL,
                  status TEXT NOT NULL,
                  application_type TEXT NOT NULL DEFAULT 'unknown',
                  analysis_json TEXT,
                  analysis_schema_version INTEGER NOT NULL DEFAULT 1,
                  analysis_provenance_json TEXT
                )
                """
            )
            self._ensure_column(conn, "jobs", "source_url", "TEXT")
            self._ensure_column(conn, "jobs", "application_type", "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(conn, "jobs", "analysis_json", "TEXT")
            self._ensure_column(conn, "jobs", "analysis_schema_version", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "jobs", "analysis_provenance_json", "TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_analysis_versions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  job_id INTEGER NOT NULL,
                  schema_version INTEGER NOT NULL,
                  analysis_json TEXT NOT NULL,
                  provenance_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_column(conn, "job_analysis_versions", "provenance_json", "TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_job_analysis_versions_job_id
                ON job_analysis_versions(job_id, id)
                """
            )
            self._migrate_saved_analysis_payloads(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_chat_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  job_id INTEGER NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  used_web_search INTEGER NOT NULL DEFAULT 0,
                  citations_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_column(conn, "job_chat_messages", "used_web_search", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "job_chat_messages", "citations_json", "TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_job_chat_messages_job_id
                ON job_chat_messages(job_id, id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS global_chat_sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS global_chat_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id INTEGER,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  used_web_search INTEGER NOT NULL DEFAULT 0,
                  citations_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(session_id) REFERENCES global_chat_sessions(id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_column(conn, "global_chat_messages", "session_id", "INTEGER")
            self._ensure_global_chat_session_migration(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_global_chat_messages_session_id
                ON global_chat_messages(session_id, id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prep_plans (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT NOT NULL,
                  source TEXT NOT NULL,
                  timeline_days INTEGER NOT NULL,
                  hours_per_day REAL NOT NULL,
                  plan_json TEXT NOT NULL,
                  schema_version INTEGER NOT NULL DEFAULT 1,
                  revision INTEGER NOT NULL DEFAULT 1,
                  provenance_json TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "prep_plans", "schema_version", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "prep_plans", "revision", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "prep_plans", "provenance_json", "TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prep_plan_versions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  prep_plan_id INTEGER NOT NULL,
                  revision INTEGER NOT NULL,
                  schema_version INTEGER NOT NULL,
                  plan_json TEXT NOT NULL,
                  provenance_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(prep_plan_id) REFERENCES prep_plans(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_prep_plan_versions_plan_id
                ON prep_plan_versions(prep_plan_id, revision)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resume_versions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  role_title TEXT NOT NULL,
                  company TEXT,
                  job_id INTEGER,
                  notes TEXT,
                  draft_json TEXT NOT NULL,
                  pdf_bytes BLOB NOT NULL,
                  schema_version INTEGER NOT NULL,
                  provenance_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_resume_versions_job_id
                ON resume_versions(job_id, id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_proposals (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  filename TEXT,
                  proposed_updates_json TEXT NOT NULL,
                  status TEXT NOT NULL,
                  schema_version INTEGER NOT NULL,
                  revision INTEGER NOT NULL,
                  provenance_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_proposal_versions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  proposal_id INTEGER NOT NULL,
                  revision INTEGER NOT NULL,
                  schema_version INTEGER NOT NULL,
                  proposed_updates_json TEXT NOT NULL,
                  status TEXT NOT NULL,
                  provenance_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(proposal_id) REFERENCES profile_proposals(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_profile_proposal_versions_proposal_id
                ON profile_proposal_versions(proposal_id, revision)
                """
            )
            self._bootstrap_prep_plan_versions(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leetcode_problems (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT NOT NULL,
                  url TEXT NOT NULL,
                  category TEXT NOT NULL,
                  tags_json TEXT NOT NULL,
                  note TEXT,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_leetcode_problems_updated_at
                ON leetcode_problems(updated_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_tasks (
                  id TEXT PRIMARY KEY,
                  type TEXT NOT NULL,
                  status TEXT NOT NULL,
                  input_json TEXT NOT NULL,
                  steps_json TEXT NOT NULL,
                  artifacts_json TEXT NOT NULL,
                  error TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_updated_at
                ON agent_tasks(updated_at)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _find_duplicate(self, conn: sqlite3.Connection, job: JobRecord) -> JobRecord | None:
        row = conn.execute(
            f"""
            SELECT {JOB_SELECT_COLUMNS}
            FROM jobs
            WHERE (
                source_url IS NOT NULL
                AND source_url != ''
                AND source_url = ?
              )
              OR (
                COALESCE(title, '') = COALESCE(?, '')
                AND COALESCE(company, '') = COALESCE(?, '')
                AND description = ?
              )
            """,
            (job.source_url, job.title, job.company, job.description),
        ).fetchone()
        return self._row_to_job(row) if row else None

    def _refresh_existing_job(
        self,
        conn: sqlite3.Connection,
        existing: JobRecord,
        incoming: JobRecord,
    ) -> JobRecord:
        refreshed = JobRecord(
            id=existing.id,
            source_url=incoming.source_url or existing.source_url,
            title=incoming.title or existing.title,
            company=incoming.company or existing.company,
            location=incoming.location or existing.location,
            description=incoming.description or existing.description,
            skills=incoming.skills or existing.skills,
            fit_score=incoming.fit_score,
            priority=incoming.priority,
            status=existing.status,
            application_type=incoming.application_type,
            analysis=incoming.analysis if incoming.analysis is not None else existing.analysis,
            analysis_schema_version=(
                incoming.analysis_schema_version
                if incoming.analysis is not None
                else existing.analysis_schema_version
            ),
            analysis_provenance=(
                incoming.analysis_provenance
                if incoming.analysis is not None
                else existing.analysis_provenance
            ),
        )
        conn.execute(
            """
            UPDATE jobs
            SET source_url = ?,
                title = ?,
                company = ?,
                location = ?,
                description = ?,
                skills = ?,
                fit_score = ?,
                priority = ?,
                application_type = ?,
                analysis_json = ?,
                analysis_schema_version = ?,
                analysis_provenance_json = ?
            WHERE id = ?
            """,
            (
                refreshed.source_url,
                refreshed.title,
                refreshed.company,
                refreshed.location,
                refreshed.description,
                json.dumps(refreshed.skills),
                refreshed.fit_score,
                refreshed.priority,
                refreshed.application_type.value,
                json.dumps(refreshed.analysis) if refreshed.analysis else None,
                refreshed.analysis_schema_version,
                json.dumps(refreshed.analysis_provenance.model_dump()) if refreshed.analysis_provenance else None,
                refreshed.id,
            ),
        )
        if incoming.analysis is not None and refreshed.analysis:
            self._append_analysis_version(
                conn,
                refreshed.id,
                refreshed.analysis,
                refreshed.analysis_schema_version,
                refreshed.analysis_provenance,
            )
        conn.commit()
        return refreshed

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if column_name not in {column[1] for column in columns}:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def _row_to_job(self, row: tuple) -> JobRecord:
        return JobRecord(
            id=row[0],
            source_url=row[1],
            title=row[2],
            company=row[3],
            location=row[4],
            description=row[5],
            skills=json.loads(row[6]),
            fit_score=row[7],
            priority=row[8],
            status=ApplicationStatus(row[9]),
            application_type=ApplicationType(row[10]) if len(row) > 10 and row[10] else ApplicationType.UNKNOWN,
            analysis=json.loads(row[11]) if len(row) > 11 and row[11] else None,
            analysis_schema_version=row[12] if len(row) > 12 else None,
            analysis_provenance=json.loads(row[13]) if len(row) > 13 and row[13] else None,
        )

    def _row_to_chat_message(self, row: tuple) -> JobChatMessage:
        return JobChatMessage(
            id=row[0],
            job_id=row[1],
            role=ChatRole(row[2]),
            content=row[3],
            used_web_search=bool(row[4]),
            citations=json.loads(row[5]) if row[5] else [],
            created_at=row[6],
        )

    def _row_to_global_chat_session(self, row: tuple) -> GlobalChatSession:
        return GlobalChatSession(
            id=row[0],
            title=row[1],
            created_at=row[2],
            updated_at=row[3],
        )

    def _row_to_global_chat_message(self, row: tuple) -> GlobalChatMessage:
        return GlobalChatMessage(
            id=row[0],
            session_id=row[1],
            role=ChatRole(row[2]),
            content=row[3],
            used_web_search=bool(row[4]),
            citations=json.loads(row[5]) if row[5] else [],
            created_at=row[6],
        )

    def _row_to_prep_plan(self, row: tuple) -> PrepPlan:
        payload = json.loads(row[5])
        return PrepPlan(
            id=row[0],
            title=row[1],
            source=row[2],
            timeline_days=row[3],
            hours_per_day=row[4],
            days=payload.get("days", []),
            schema_version=row[6],
            revision=row[7],
            provenance=json.loads(row[8]) if row[8] else None,
            workflow_graph=payload.get("workflow_graph"),
            workflow_run=payload.get("workflow_run"),
            evaluation=payload.get("evaluation"),
            created_at=row[9],
            updated_at=row[10],
        )

    def _row_to_leetcode_problem(self, row: tuple) -> LeetCodeProblem:
        return LeetCodeProblem(
            id=row[0],
            title=row[1],
            url=row[2],
            category=row[3],
            tags=json.loads(row[4]) if row[4] else [],
            note=row[5],
            status=LeetCodeStatus(row[6]),
            created_at=row[7],
            updated_at=row[8],
        )

    def _row_to_agent_task(self, row: tuple) -> AgentTask:
        return AgentTask(
            id=row[0],
            type=AgentTaskType(row[1]),
            status=AgentTaskStatus(row[2]),
            input=json.loads(row[3]) if row[3] else {},
            steps=[AgentTaskStep.model_validate(step) for step in json.loads(row[4] or "[]")],
            artifacts=json.loads(row[5]) if row[5] else {},
            error=row[6],
            created_at=row[7],
            updated_at=row[8],
        )

    def _write_agent_task_steps(self, task: AgentTask) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_tasks
                SET steps_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps([step.model_dump() for step in task.steps]),
                    task.updated_at,
                    task.id,
                ),
            )
            conn.commit()

    def _finish_agent_task_step(
        self,
        task_id: str,
        name: str,
        status: str,
        summary: str | None = None,
        error: str | None = None,
    ) -> AgentTask | None:
        task = self.get_agent_task(task_id)
        if task is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        for step in reversed(task.steps):
            if step.name == name and step.status == "running":
                step.status = status
                step.completed_at = now
                if summary is not None:
                    step.summary = summary
                if error is not None:
                    step.error = error
                break
        else:
            task.steps.append(
                AgentTaskStep(
                    name=name,
                    status=status,
                    started_at=now,
                    completed_at=now,
                    summary=summary,
                    error=error,
                )
            )
        task.updated_at = now
        self._write_agent_task_steps(task)
        return task

    def _resolve_global_chat_session(
        self,
        session_id: int | None = None,
        create_if_missing: bool = False,
    ) -> GlobalChatSession:
        if session_id is not None:
            session = self.get_global_chat_session(session_id)
            if session:
                return session
            if not create_if_missing:
                return GlobalChatSession(id=None)

        sessions = self.list_global_chat_sessions()
        if sessions:
            return sessions[0]
        if create_if_missing:
            return self.create_global_chat_session()
        return GlobalChatSession(id=None)

    def _ensure_global_chat_session_migration(self, conn: sqlite3.Connection) -> None:
        unassigned_count = conn.execute(
            "SELECT COUNT(*) FROM global_chat_messages WHERE session_id IS NULL"
        ).fetchone()[0]
        if unassigned_count == 0:
            return

        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            """
            INSERT INTO global_chat_sessions (title, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            ("Previous conversation", now, now),
        )
        conn.execute(
            "UPDATE global_chat_messages SET session_id = ? WHERE session_id IS NULL",
            (cursor.lastrowid,),
        )

    def get_job(self, job_id: int) -> JobDetail | None:
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {JOB_SELECT_COLUMNS}
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        job = self._row_to_job(row)
        return JobDetail(job=job, analysis=job.analysis)

    def list_prep_plan_versions(self, plan_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, prep_plan_id, revision, schema_version, plan_json, provenance_json, created_at
                FROM prep_plan_versions
                WHERE prep_plan_id = ?
                ORDER BY revision ASC, id ASC
                """,
                (plan_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "prep_plan_id": row[1],
                "revision": row[2],
                "schema_version": row[3],
                "plan": json.loads(row[4]),
                "provenance": json.loads(row[5]) if row[5] else None,
                "created_at": row[6],
            }
            for row in rows
        ]

    def save_resume_version(self, resume: ResumeVersion, pdf: bytes) -> ResumeVersion:
        created_at = resume.created_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO resume_versions (
                  role_title, company, job_id, notes, draft_json, pdf_bytes, schema_version,
                  provenance_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resume.role_title,
                    resume.company,
                    resume.job_id,
                    resume.notes,
                    json.dumps(resume.draft),
                    pdf,
                    resume.schema_version,
                    json.dumps(resume.provenance.model_dump()),
                    created_at,
                ),
            )
            conn.commit()
        return resume.model_copy(update={"id": cursor.lastrowid, "created_at": created_at})

    def list_resume_versions(self) -> list[ResumeVersion]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role_title, company, job_id, notes, draft_json, schema_version, provenance_json, created_at
                FROM resume_versions
                ORDER BY id DESC
                """
            ).fetchall()
        return [self._row_to_resume_version(row) for row in rows]

    def get_resume_pdf(self, resume_id: int) -> bytes | None:
        with self._connect() as conn:
            row = conn.execute("SELECT pdf_bytes FROM resume_versions WHERE id = ?", (resume_id,)).fetchone()
        return row[0] if row else None

    def create_profile_proposal(self, proposal: ProfileProposal) -> ProfileProposal:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO profile_proposals (
                  filename, proposed_updates_json, status, schema_version, revision, provenance_json,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.filename,
                    json.dumps(proposal.proposed_updates),
                    proposal.status,
                    proposal.schema_version,
                    proposal.revision,
                    json.dumps(proposal.provenance.model_dump()),
                    now,
                    now,
                ),
            )
            saved = proposal.model_copy(update={"id": cursor.lastrowid, "created_at": now, "updated_at": now})
            self._append_profile_proposal_version(conn, saved)
            conn.commit()
        return saved

    def update_profile_proposal(
        self,
        proposal_id: int,
        proposed_updates: dict[str, list[str]] | None = None,
        status: str | None = None,
        provenance=None,
    ) -> ProfileProposal | None:
        current = self.get_profile_proposal(proposal_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={
                "proposed_updates": proposed_updates if proposed_updates is not None else current.proposed_updates,
                "status": status or current.status,
                "revision": current.revision + 1,
                "provenance": provenance or current.provenance,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE profile_proposals
                SET proposed_updates_json = ?, status = ?, revision = ?, provenance_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(updated.proposed_updates),
                    updated.status,
                    updated.revision,
                    json.dumps(updated.provenance.model_dump()),
                    updated.updated_at,
                    proposal_id,
                ),
            )
            self._append_profile_proposal_version(conn, updated)
            conn.commit()
        return updated

    def get_profile_proposal(self, proposal_id: int) -> ProfileProposal | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, filename, proposed_updates_json, status, schema_version, revision,
                       provenance_json, created_at, updated_at
                FROM profile_proposals
                WHERE id = ?
                """,
                (proposal_id,),
            ).fetchone()
        return self._row_to_profile_proposal(row) if row else None

    def list_profile_proposal_versions(self, proposal_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, proposal_id, revision, schema_version, proposed_updates_json, status,
                       provenance_json, created_at
                FROM profile_proposal_versions
                WHERE proposal_id = ?
                ORDER BY revision ASC, id ASC
                """,
                (proposal_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "proposal_id": row[1],
                "revision": row[2],
                "schema_version": row[3],
                "proposed_updates": json.loads(row[4]),
                "status": row[5],
                "provenance": json.loads(row[6]),
                "created_at": row[7],
            }
            for row in rows
        ]

    def list_job_analysis_versions(self, job_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, job_id, schema_version, analysis_json, provenance_json, created_at
                FROM job_analysis_versions
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "job_id": row[1],
                "schema_version": row[2],
                "analysis": json.loads(row[3]),
                "provenance": json.loads(row[4]) if row[4] else None,
                "created_at": row[5],
            }
            for row in rows
        ]

    def _append_analysis_version(
        self,
        conn: sqlite3.Connection,
        job_id: int,
        analysis: dict,
        schema_version: int | None,
        provenance=None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO job_analysis_versions (job_id, schema_version, analysis_json, provenance_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                job_id,
                schema_version or CURRENT_ANALYSIS_SCHEMA_VERSION,
                json.dumps(analysis),
                json.dumps(provenance.model_dump()) if provenance else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def _append_prep_plan_version(
        self,
        conn: sqlite3.Connection,
        plan_id: int,
        plan: PrepPlan,
        created_at: str,
    ) -> None:
        payload = plan.model_dump(exclude={"id", "created_at", "updated_at"}, mode="json")
        conn.execute(
            """
            INSERT INTO prep_plan_versions (
              prep_plan_id, revision, schema_version, plan_json, provenance_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                plan.revision,
                plan.schema_version,
                json.dumps(payload),
                json.dumps(plan.provenance.model_dump()) if plan.provenance else None,
                created_at,
            ),
        )

    def _bootstrap_prep_plan_versions(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT id, plan_json, schema_version, revision, provenance_json, created_at
            FROM prep_plans
            WHERE NOT EXISTS (
              SELECT 1 FROM prep_plan_versions WHERE prep_plan_versions.prep_plan_id = prep_plans.id
            )
            """
        ).fetchall()
        for plan_id, payload, schema_version, revision, provenance, created_at in rows:
            conn.execute(
                """
                INSERT INTO prep_plan_versions (
                  prep_plan_id, revision, schema_version, plan_json, provenance_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (plan_id, revision, schema_version, payload, provenance, created_at),
            )

    def _append_profile_proposal_version(self, conn: sqlite3.Connection, proposal: ProfileProposal) -> None:
        conn.execute(
            """
            INSERT INTO profile_proposal_versions (
              proposal_id, revision, schema_version, proposed_updates_json, status, provenance_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.id,
                proposal.revision,
                proposal.schema_version,
                json.dumps(proposal.proposed_updates),
                proposal.status,
                json.dumps(proposal.provenance.model_dump()),
                proposal.updated_at or datetime.now(timezone.utc).isoformat(),
            ),
        )

    def _row_to_resume_version(self, row: tuple) -> ResumeVersion:
        return ResumeVersion(
            id=row[0],
            role_title=row[1],
            company=row[2],
            job_id=row[3],
            notes=row[4],
            draft=json.loads(row[5]),
            schema_version=row[6],
            provenance=json.loads(row[7]),
            created_at=row[8],
        )

    def _row_to_profile_proposal(self, row: tuple) -> ProfileProposal:
        return ProfileProposal(
            id=row[0],
            filename=row[1],
            proposed_updates=json.loads(row[2]),
            status=row[3],
            schema_version=row[4],
            revision=row[5],
            provenance=json.loads(row[6]),
            created_at=row[7],
            updated_at=row[8],
        )

    def _migrate_saved_analysis_payloads(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT id, analysis_json, analysis_schema_version
            FROM jobs
            WHERE analysis_json IS NOT NULL
            """
        ).fetchall()
        for job_id, analysis_json, schema_version in rows:
            original = json.loads(analysis_json)
            migrated, migrated_version = migrate_analysis_payload(original, schema_version)
            if migrated == original and migrated_version == schema_version:
                continue
            self._append_analysis_version(conn, job_id, original, schema_version)
            conn.execute(
                """
                UPDATE jobs
                SET analysis_json = ?, analysis_schema_version = ?
                WHERE id = ?
                """,
                (json.dumps(migrated), migrated_version, job_id),
            )
            if migrated is not None:
                self._append_analysis_version(conn, job_id, migrated, migrated_version)
