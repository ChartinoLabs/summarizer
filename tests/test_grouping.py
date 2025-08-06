"""Tests for the grouping module."""

import unittest
from datetime import datetime, timedelta

from summarizer.grouping import group_group_conversations
from summarizer.models import Message, SpaceType, User


class TestGroupingBugFix(unittest.TestCase):
    """Test cases for the cross-space grouping bug fix."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Create test users
        self.karthik = User(id="user1", display_name="Karthik Ravishankar")
        self.christopher = User(id="user2", display_name="Christopher Hart")
        self.michael = User(id="user3", display_name="Michael Neblett")
        self.blake = User(id="user4", display_name="Blake Becton")
        self.craig = User(id="user5", display_name="Craig Lien")

        # Create messages from the AskCX test automation space
        self.askcx_messages = [
            Message(
                id="msg1",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.karthik,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 15, 2),
                content="Hi Team, I was exploring the CXTM REST APIs...",
            ),
            Message(
                id="msg2",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.christopher,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 20, 20),
                content="Does it work on a different browser?",
            ),
            Message(
                id="msg3",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.karthik,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 21, 49),
                content="Yes, works on Safari. But not on Chrome even after clearing the cache.",
            ),
            Message(
                id="msg4",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.christopher,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 22, 34),
                content="Does it work in Chrome on incognito mode?",
            ),
            Message(
                id="msg5",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.karthik,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 24, 28),
                content="Yes, Works fine in incognito.",
            ),
            Message(
                id="msg6",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.christopher,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 24, 48),
                content="When you say you cleared cache, does that include cookies?",
            ),
            Message(
                id="msg7",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.karthik,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 27, 49),
                content="Oops, I didn't clear the cookies. It works perfectly now after doing that. Thanks, Christopher.",
            ),
        ]

        # Create messages from a different space that happened around the same time
        self.other_space_messages = [
            Message(
                id="msg8",
                space_id="space_other",
                space_type=SpaceType.GROUP,
                space_name="Other Team Space",
                sender=self.michael,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 17, 56),
                content="Christopher - I believe those were listed as hybrid roles...",
            ),
            Message(
                id="msg9",
                space_id="space_other",
                space_type=SpaceType.GROUP,
                space_name="Other Team Space",
                sender=self.blake,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 19, 25),
                content="Morning team! Unexpected change of plans this morning...",
            ),
            Message(
                id="msg10",
                space_id="space_other",
                space_type=SpaceType.GROUP,
                space_name="Other Team Space",
                sender=self.craig,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 22, 15),
                content="Good Morning!",
            ),
        ]

    def test_cross_space_grouping_bug_is_fixed(self) -> None:
        """Test that messages from different spaces are not incorrectly grouped together.

        This test reproduces the bug described in the user's report where messages
        from different WebEx spaces were incorrectly grouped into the same conversation.
        The fix ensures that messages are grouped by space_id first before applying
        conversation logic.
        """
        # Combine all messages (this simulates the bug scenario)
        all_messages = self.askcx_messages + self.other_space_messages

        # Use a 15-minute context window (same as default)
        context_window = timedelta(minutes=15)

        # Group the conversations
        conversations = group_group_conversations(all_messages, context_window)

        # Verify that we get separate conversations for each space
        askcx_conversations = [c for c in conversations if c.space_id == "space_askcx"]
        other_conversations = [c for c in conversations if c.space_id == "space_other"]

        # Should have at least one conversation from each space
        self.assertGreater(
            len(askcx_conversations), 0, "Should have conversations from AskCX space"
        )
        self.assertGreater(
            len(other_conversations), 0, "Should have conversations from other space"
        )

        # Verify that no conversation contains messages from multiple spaces
        for conversation in conversations:
            space_ids = {msg.space_id for msg in conversation.messages}
            self.assertEqual(
                len(space_ids),
                1,
                f"Conversation {conversation.id} contains messages from multiple spaces: {space_ids}",
            )

        # Verify that AskCX conversations only contain AskCX participants
        for conversation in askcx_conversations:
            participant_names = {p.display_name for p in conversation.participants}
            expected_askcx_participants = {"Karthik Ravishankar", "Christopher Hart"}
            unexpected_participants = participant_names - expected_askcx_participants
            self.assertEqual(
                len(unexpected_participants),
                0,
                f"AskCX conversation contains unexpected participants: {unexpected_participants}",
            )

        # Verify that other space conversations don't contain AskCX participants
        for conversation in other_conversations:
            participant_names = {p.display_name for p in conversation.participants}
            askcx_participants = {"Karthik Ravishankar", "Christopher Hart"}
            contaminating_participants = participant_names & askcx_participants
            self.assertEqual(
                len(contaminating_participants),
                0,
                f"Other space conversation contains AskCX participants: {contaminating_participants}",
            )

    def test_single_space_grouping_still_works(self) -> None:
        """Test that grouping within a single space still works correctly."""
        # Use only AskCX messages
        context_window = timedelta(minutes=15)

        conversations = group_group_conversations(self.askcx_messages, context_window)

        # Should have exactly one conversation (all messages are within time window and same space)
        self.assertEqual(
            len(conversations),
            1,
            "Should group all AskCX messages into one conversation",
        )

        conversation = conversations[0]

        # Verify all messages are included
        self.assertEqual(len(conversation.messages), len(self.askcx_messages))

        # Verify correct participants
        participant_names = {p.display_name for p in conversation.participants}
        expected_participants = {"Karthik Ravishankar", "Christopher Hart"}
        self.assertEqual(participant_names, expected_participants)

        # Verify space information
        self.assertEqual(conversation.space_id, "space_askcx")
        self.assertEqual(conversation.space_type, SpaceType.GROUP)


if __name__ == "__main__":
    unittest.main()
