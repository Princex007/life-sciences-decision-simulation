"""Backward-compatible entry point for the configurable US launch example."""
from app.run_simulation import main
from app.domain.definitions import SimulationDefinition

def build_demo_definition():
    """Load the bundled demonstration from its JSON source of truth."""
    return SimulationDefinition.from_json("examples/us_drug_launch.json")

if __name__ == "__main__":
    main()
