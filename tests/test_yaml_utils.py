"""Tests for YAML utilities."""

from pathlib import Path

import pytest
import yaml

from summarizer.yaml_utils import TeamYAML, UserMember, load_users_from_yaml


class TestUserMember:
    """Tests for UserMember model validation."""

    def test_valid_user_member(self) -> None:
        """Test that a valid user member is created successfully."""
        user = UserMember(
            username="jsmith",
            cec_id="jsmith",
            full_name="John Smith",
            reports_to="Jane Doe (jdoe)",
        )
        assert user.username == "jsmith"
        assert user.cec_id == "jsmith"
        assert user.full_name == "John Smith"
        assert user.reports_to == "Jane Doe (jdoe)"

    def test_user_member_without_reports_to(self) -> None:
        """Test that reports_to field is optional."""
        user = UserMember(username="jsmith", cec_id="jsmith", full_name="John Smith")
        assert user.reports_to is None

    def test_empty_cec_id_raises_error(self) -> None:
        """Test that empty CEC ID raises validation error."""
        with pytest.raises(ValueError, match="CEC ID cannot be empty"):
            UserMember(username="jsmith", cec_id="", full_name="John Smith")

    def test_whitespace_cec_id_raises_error(self) -> None:
        """Test that whitespace-only CEC ID raises validation error."""
        with pytest.raises(ValueError, match="CEC ID cannot be empty"):
            UserMember(username="jsmith", cec_id="   ", full_name="John Smith")


class TestTeamYAML:
    """Tests for TeamYAML model validation."""

    def test_valid_team_yaml(self) -> None:
        """Test that a valid team YAML structure is parsed correctly."""
        team = TeamYAML(
            name="test-team",
            description="Test team description",
            members=[
                UserMember(username="jsmith", cec_id="jsmith", full_name="John Smith"),
                UserMember(username="jdoe", cec_id="jdoe", full_name="Jane Doe"),
            ],
        )
        assert team.name == "test-team"
        assert team.description == "Test team description"
        assert len(team.members) == 2

    def test_team_yaml_without_members(self) -> None:
        """Test that team without members is valid."""
        team = TeamYAML(name="empty-team")
        assert team.name == "empty-team"
        assert team.members == []


class TestLoadUsersFromYAML:
    """Tests for load_users_from_yaml function."""

    def test_load_users_success(self, tmp_path: Path) -> None:
        """Test successful loading of users from a YAML file."""
        yaml_content = """
name: test-team
description: Test team
members:
  - username: jsmith
    cec_id: jsmith
    full_name: John Smith
    reports_to: Jane Doe (jdoe)
  - username: jdoe
    cec_id: jdoe
    full_name: Jane Doe
    reports_to: Manager (manager)
"""
        yaml_file = tmp_path / "test_users.yaml"
        yaml_file.write_text(yaml_content)

        emails = load_users_from_yaml(yaml_file)

        assert len(emails) == 2
        assert "jsmith@cisco.com" in emails
        assert "jdoe@cisco.com" in emails

    def test_load_users_file_not_found(self) -> None:
        """Test that FileNotFoundError is raised for non-existent file."""
        with pytest.raises(FileNotFoundError, match="YAML file not found"):
            load_users_from_yaml("/nonexistent/file.yaml")

    def test_load_users_empty_file(self, tmp_path: Path) -> None:
        """Test that ValueError is raised for empty YAML file."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")

        with pytest.raises(ValueError, match="YAML file .* is empty"):
            load_users_from_yaml(yaml_file)

    def test_load_users_invalid_yaml(self, tmp_path: Path) -> None:
        """Test that YAMLError is raised for invalid YAML syntax."""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("name: test\nmembers:\n  - invalid yaml: [")

        with pytest.raises(yaml.YAMLError):
            load_users_from_yaml(yaml_file)

    def test_load_users_missing_required_fields(self, tmp_path: Path) -> None:
        """Test that ValueError is raised when required fields are missing."""
        yaml_content = """
name: test-team
members:
  - username: jsmith
    full_name: John Smith
"""
        yaml_file = tmp_path / "missing_fields.yaml"
        yaml_file.write_text(yaml_content)

        with pytest.raises(ValueError, match="Invalid YAML structure"):
            load_users_from_yaml(yaml_file)

    def test_load_users_no_members(self, tmp_path: Path) -> None:
        """Test that empty list is returned when no members exist."""
        yaml_content = """
name: test-team
description: Team with no members
members: []
"""
        yaml_file = tmp_path / "no_members.yaml"
        yaml_file.write_text(yaml_content)

        emails = load_users_from_yaml(yaml_file)

        assert emails == []

    def test_load_users_cec_id_formatting(self, tmp_path: Path) -> None:
        """Test that CEC IDs are correctly formatted as email addresses."""
        yaml_content = """
name: test-team
members:
  - username: user1
    cec_id: user1
    full_name: User One
  - username: user2
    cec_id: user2
    full_name: User Two
"""
        yaml_file = tmp_path / "format_test.yaml"
        yaml_file.write_text(yaml_content)

        emails = load_users_from_yaml(yaml_file)

        assert all(email.endswith("@cisco.com") for email in emails)
        assert all("@" in email for email in emails)
