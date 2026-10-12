"""Domain-neutral world state backed by arbitrary named variables."""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

class WorldState(BaseModel):
    """Simulation clock plus user-defined world variables."""
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    time: int = 0
    variables: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def collect_extra_variables(cls, value):
        """Accept legacy direct variable keywords and normalize them to a map."""
        if not isinstance(value, dict):
            return value
        value = dict(value)
        variables = dict(value.get("variables", {}))
        for key in list(value):
            if key not in {"time", "variables"}:
                variables[key] = value.pop(key)
        value["variables"] = variables
        return value

    def get(self, name: str, default: Any = None) -> Any:
        """Read a world variable without coupling callers to its domain."""
        return self.variables.get(name, default)

    def set(self, name: str, value: Any) -> None:
        """Set a named world variable."""
        if name == "time":
            self.time = int(value)
        else:
            self.variables[name] = value

    def as_variables(self) -> dict[str, Any]:
        """Return a copy of the named variable map."""
        return dict(self.variables)

    def __getattr__(self, name: str) -> Any:
        variables = super().__getattribute__("variables")
        if name in variables:
            return variables[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name not in {"time", "variables"} and "variables" in self.__dict__:
            self.variables[name] = value
        else:
            super().__setattr__(name, value)
