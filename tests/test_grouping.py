"""Tests for the grouping module."""

import unittest
from datetime import datetime, timedelta

from summarizer.common.grouping import group_group_conversations
from summarizer.common.models import Message, SpaceType, User


class TestGroupingBugFix(unittest.TestCase):
    """Test cases for the cross-space grouping bug fix."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Create test users
        self.user_a = User(id="user1", display_name="Alice Smith")
        self.user_b = User(id="user2", display_name="Bob Johnson")
        self.user_c = User(id="user3", display_name="Charlie Brown")
        self.user_d = User(id="user4", display_name="Diana Prince")
        self.user_e = User(id="user5", display_name="Eve Wilson")

        # Create messages from the AskCX test automation space
        self.askcx_messages = [
            Message(
                id="msg1",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.user_a,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 15, 2),
                content="Hi Team, I was exploring the CXTM REST APIs...",
            ),
            Message(
                id="msg2",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.user_b,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 20, 20),
                content="Does it work on a different browser?",
            ),
            Message(
                id="msg3",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.user_a,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 21, 49),
                content=(
                    "Yes, works on Safari. But not on Chrome even after clearing "
                    "the cache."
                ),
            ),
            Message(
                id="msg4",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.user_b,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 22, 34),
                content="Does it work in Chrome on incognito mode?",
            ),
            Message(
                id="msg5",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.user_a,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 24, 28),
                content="Yes, Works fine in incognito.",
            ),
            Message(
                id="msg6",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.user_b,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 24, 48),
                content="When you say you cleared cache, does that include cookies?",
            ),
            Message(
                id="msg7",
                space_id="space_askcx",
                space_type=SpaceType.GROUP,
                space_name="AskCX Test Automation",
                sender=self.user_a,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 27, 49),
                content=(
                    "Oops, I didn't clear the cookies. It works perfectly now "
                    "after doing that. Thanks, Bob."
                ),
            ),
        ]

        # Create messages from a different space that happened around the same time
        # Bob participates in this space too
        self.other_space_messages = [
            Message(
                id="msg8",
                space_id="space_other",
                space_type=SpaceType.GROUP,
                space_name="Other Team Space",
                sender=self.user_c,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 17, 56),
                content="Bob - I believe those were listed as hybrid roles...",
            ),
            Message(
                id="msg9",
                space_id="space_other",
                space_type=SpaceType.GROUP,
                space_name="Other Team Space",
                sender=self.user_d,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 19, 25),
                content="Morning team! Unexpected change of plans this morning...",
            ),
            Message(
                id="msg10",
                space_id="space_other",
                space_type=SpaceType.GROUP,
                space_name="Other Team Space",
                sender=self.user_b,  # Bob responds in this space
                recipients=[],
                timestamp=datetime(2025, 8, 6, 8, 22, 15),
                content="Thanks for the update!",
            ),
        ]

    def test_cross_space_grouping_bug_is_fixed(self) -> None:
        """Test that messages from different spaces are not incorrectly grouped.

        This test reproduces the bug described in the user's report where messages
        from different WebEx spaces were incorrectly grouped into the same conversation.
        The fix ensures that messages are grouped by space_id first before applying
        conversation logic.
        """
        # Combine all messages (this simulates the bug scenario)
        all_messages = self.askcx_messages + self.other_space_messages

        # Use a 15-minute context window (same as default)
        context_window = timedelta(minutes=15)

        # Group the conversations - use Bob Johnson's user ID
        authenticated_user_id = "user2"  # Bob Johnson's user ID
        conversations = group_group_conversations(
            all_messages, context_window, authenticated_user_id
        )

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
                f"Conversation {conversation.id} contains messages from multiple "
                f"spaces: {space_ids}",
            )

        # Verify that AskCX conversations only contain AskCX participants
        for conversation in askcx_conversations:
            participant_names = {p.display_name for p in conversation.participants}
            expected_askcx_participants = {"Alice Smith", "Bob Johnson"}
            unexpected_participants = participant_names - expected_askcx_participants
            self.assertEqual(
                len(unexpected_participants),
                0,
                f"AskCX conversation contains unexpected participants: "
                f"{unexpected_participants}",
            )

        # Verify that other space conversations contain the expected participants
        # Bob participates in both spaces, so he should appear in both
        for conversation in other_conversations:
            participant_names = {p.display_name for p in conversation.participants}
            # Bob should be in the other space since he sent a message there
            self.assertIn(
                "Bob Johnson",
                participant_names,
                f"Other space conversation should contain Bob Johnson: "
                f"{participant_names}",
            )

    def test_single_space_grouping_still_works(self) -> None:
        """Test that grouping within a single space still works correctly."""
        # Use only AskCX messages
        context_window = timedelta(minutes=15)

        authenticated_user_id = "user2"  # Bob Johnson's user ID
        conversations = group_group_conversations(
            self.askcx_messages, context_window, authenticated_user_id
        )

        # Should have exactly one conversation (all messages are within time window
        # and same space)
        self.assertEqual(
            len(conversations),
            1,
            "Should group all AskCX messages into one conversation",
        )

        conversation = conversations[0]

        # Verify that the conversation includes messages within the context window
        # Bob's first message is at 8:20:20, with a 15-minute window (8:05:20 - 8:35:20)
        # This should include messages 2-7 (msg1 at 8:15:02 is outside the window)
        self.assertGreaterEqual(len(conversation.messages), 6)
        self.assertLessEqual(len(conversation.messages), len(self.askcx_messages))

        # Verify correct participants
        participant_names = {p.display_name for p in conversation.participants}
        expected_participants = {"Alice Smith", "Bob Johnson"}
        self.assertEqual(participant_names, expected_participants)

        # Verify space information
        self.assertEqual(conversation.space_id, "space_askcx")
        self.assertEqual(conversation.space_type, SpaceType.GROUP)

    def test_non_participant_conversation_leak_bug(self) -> None:
        """Test conversations are not created when user is not a participant.

        This test reproduces the bug where conversations are displayed even when
        the authenticated user (Bob Johnson) is not one of the participants.
        The bug occurs because group_group_conversations incorrectly uses the first
        message sender's ID as the user_id instead of the authenticated user's ID.
        """
        # Create messages in a group space where Bob Johnson is NOT a participant
        # but other users are talking
        user_f = User(id="user_f", display_name="Frank Miller")
        user_g = User(id="user_g", display_name="Grace Lee")

        # Messages from a space where Bob is not a participant
        non_participant_messages = [
            Message(
                id="msg_leak1",
                space_id="space_external",
                space_type=SpaceType.GROUP,
                space_name="External Team Session",
                sender=user_f,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 11, 56, 53),
                content="Hi Everyone, Thanks for attending the session...",
            ),
            Message(
                id="msg_leak2",
                space_id="space_external",
                space_type=SpaceType.GROUP,
                space_name="External Team Session",
                sender=user_g,
                recipients=[],
                timestamp=datetime(2025, 8, 6, 12, 0, 55),
                content="this was great! Big thanks to everyone who helped guide us.",
            ),
        ]

        # Mix with messages where Bob IS a participant (from existing test data)
        all_messages = non_participant_messages + self.askcx_messages

        context_window = timedelta(minutes=15)

        # The bug: group_group_conversations should NOT create conversations
        # for spaces where Bob Johnson (user2) is not a participant
        authenticated_user_id = "user2"  # Bob Johnson's user ID
        conversations = group_group_conversations(
            all_messages, context_window, authenticated_user_id
        )

        # Check for conversations from the External space
        external_conversations = [
            c for c in conversations if c.space_id == "space_external"
        ]

        # BUG: Currently this will fail because the function incorrectly creates
        # conversations even when Bob is not a participant
        # After the fix, this should pass
        self.assertEqual(
            len(external_conversations),
            0,
            "Should not create conversations where user is not a participant. "
            f"Found {len(external_conversations)} conversations in External space "
            "where Bob Johnson is not a participant.",
        )

        # Verify conversations are still created for spaces where Bob IS a participant
        askcx_conversations = [c for c in conversations if c.space_id == "space_askcx"]
        self.assertGreater(
            len(askcx_conversations),
            0,
            "Should still create conversations where authenticated user participates",
        )


if __name__ == "__main__":
    unittest.main()
