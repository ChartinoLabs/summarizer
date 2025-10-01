"""YAML file parsing utilities for user management."""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class UserMember(BaseModel):
    """Represents a user member from a YAML team file.

    This model validates and extracts user information from team YAML files
    that follow the organizational structure with members having cec_id fields.
    """

    username: str
    cec_id: str
    full_name: str
    reports_to: str | None = None

    @field_validator("cec_id")
    @classmethod
    def validate_cec_id(cls, v: str) -> str:
        """Ensure CEC ID is not empty."""
        if not v or not v.strip():
            raise ValueError("CEC ID cannot be empty")
        return v.strip()


class TeamYAML(BaseModel):
    """Represents the full structure of a team YAML file."""

    name: str
    description: str | None = None
    members: list[UserMember] = Field(default_factory=list)


def load_users_from_yaml(file_path: str | Path) -> list[str]:
    """Load user email addresses from a team YAML file.

    This function reads a YAML file containing team member information and
    extracts CEC IDs, converting them to Cisco email addresses in the format
    {cec_id}@cisco.com.

    Expected YAML file structure:
        name: team-name
        description: Optional team description
        members:
          - username: jsmith
            cec_id: jsmith
            full_name: John Smith
            reports_to: Manager Name (manager_cec)
          - username: jdoe
            cec_id: jdoe
            full_name: Jane Doe
            reports_to: Manager Name (manager_cec)

    Args:
        file_path: Path to the YAML file containing user information

    Returns:
        List of email addresses in the format cec_id@cisco.com

    Raises:
        FileNotFoundError: If the specified YAML file does not exist
        ValueError: If the YAML file is invalid or missing required fields
        yaml.YAMLError: If the YAML file cannot be parsed
    """
    path = Path(file_path)

    if not path.exists():
        logger.error("YAML file not found: %s", file_path)
        raise FileNotFoundError(f"YAML file not found: {file_path}")

    try:
        with path.open("r") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error("Failed to parse YAML file %s: %s", file_path, e)
        raise

    if not data:
        logger.error("YAML file %s is empty", file_path)
        raise ValueError(f"YAML file {file_path} is empty")

    try:
        # Parse and validate the team structure
        team = TeamYAML(**data)
    except Exception as e:
        logger.error("Invalid YAML structure in %s: %s", file_path, e)
        raise ValueError(f"Invalid YAML structure in {file_path}: {e}") from e

    if not team.members:
        logger.warning("No members found in YAML file %s", file_path)
        return []

    # Extract CEC IDs and convert to email addresses
    email_addresses = [f"{member.cec_id}@cisco.com" for member in team.members]

    logger.info(
        "Loaded %d user email addresses from %s", len(email_addresses), file_path
    )
    return email_addresses
