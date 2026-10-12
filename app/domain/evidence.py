"""Typed evidence records with compatibility for the original demo schema."""

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    evidence_id: str = Field(validation_alias=AliasChoices("evidence_id", "id"))
    title: str
    content: str
    source: str = "synthetic fixture"
    source_type: str = "synthetic"
    date: str | int | None = Field(default=None, validation_alias=AliasChoices("date", "timestamp"))
    domain: str = "general"
    tags: list[str] = Field(default_factory=list)
    reliability_label: str = "unrated"
    applicable_agents: list[str] = Field(default_factory=list,
        validation_alias=AliasChoices("applicable_agents", "visible_to_agents"))
    related_variables: list[str] = Field(default_factory=list)
    related_actions: list[str] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return self.evidence_id

    @property
    def timestamp(self) -> str | int | None:
        return self.date

    @property
    def visible_to_agents(self) -> list[str]:
        return self.applicable_agents
