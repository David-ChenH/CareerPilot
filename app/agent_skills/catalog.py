from pathlib import Path

import yaml
from pydantic import BaseModel, Field


DEFAULT_AGENT_SKILLS_PATH = Path(__file__).parent


class AgentSkillMetadata(BaseModel):
    id: str = Field(min_length=1)
    version: int = Field(ge=1)
    summary: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)


class AgentSkill(BaseModel):
    metadata: AgentSkillMetadata
    instructions: str


class AgentSkillCatalog:
    def __init__(self, root: Path = DEFAULT_AGENT_SKILLS_PATH) -> None:
        self.root = root

    def load(self, skill_id: str) -> AgentSkill:
        skill_path = self.root / skill_id
        instructions_path = skill_path / "SKILL.md"
        metadata_path = skill_path / "metadata.yaml"
        if not instructions_path.exists() or not metadata_path.exists():
            raise FileNotFoundError(f"Agent skill {skill_id!r} is missing SKILL.md or metadata.yaml.")

        with metadata_path.open("r", encoding="utf-8") as metadata_file:
            payload = yaml.safe_load(metadata_file) or {}
        metadata = AgentSkillMetadata.model_validate(payload)
        if metadata.id != skill_id:
            raise ValueError(f"Agent skill directory {skill_id!r} does not match metadata id {metadata.id!r}.")
        return AgentSkill(
            metadata=metadata,
            instructions=instructions_path.read_text(encoding="utf-8"),
        )
