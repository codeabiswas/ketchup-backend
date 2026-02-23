"""
Firestore database client for operational data storage.
Handles read/write operations for users, groups, feedback, and preferences.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from google.cloud import firestore
from google.oauth2 import service_account

from config.settings import settings

logger = logging.getLogger(__name__)


class FirestoreClient:
    """
    Firestore wrapper for managing ketchup operational data.
    """

    def __init__(self):
        """Initialize Firestore client with GCP credentials."""
        try:
            if settings.gcp_credentials_path:
                credentials = service_account.Credentials.from_service_account_file(
                    settings.gcp_credentials_path,
                )
                self.db = firestore.Client(
                    project=settings.gcp_project_id,
                    credentials=credentials,
                    database=settings.firestore_database,
                )
            else:
                self.db = firestore.Client(
                    project=settings.gcp_project_id,
                    database=settings.firestore_database,
                )
            logger.info("Firestore client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Firestore client: {e}")
            raise

    def create_user(self, user_data: Dict[str, Any]) -> str:
        """
        Create a new user document.

        Args:
            user_data: User information

        Returns:
            Document ID of the created user
        """
        try:
            doc_ref = self.db.collection("users").add(user_data)
            user_id = doc_ref[1].id
            logger.info(f"User created: {user_id}")
            return user_id
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            raise

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve user by ID."""
        try:
            doc = self.db.collection("users").document(user_id).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error retrieving user {user_id}: {e}")
            raise

    def update_user_preferences(
        self,
        user_id: str,
        preferences: Dict[str, Any],
    ) -> None:
        """Update user preferences."""
        try:
            preferences["updated_at"] = datetime.utcnow()
            self.db.collection("users").document(user_id).update(
                {
                    "preferences": preferences,
                },
            )
            logger.info(f"User preferences updated: {user_id}")
        except Exception as e:
            logger.error(f"Error updating user preferences: {e}")
            raise

    def create_group(self, group_data: Dict[str, Any]) -> str:
        """
        Create a new friend group.

        Args:
            group_data: Group information (members, budget, etc.)

        Returns:
            Document ID of the created group
        """
        try:
            doc_ref = self.db.collection("groups").add(group_data)
            group_id = doc_ref[1].id
            logger.info(f"Group created: {group_id}")
            return group_id
        except Exception as e:
            logger.error(f"Error creating group: {e}")
            raise

    def get_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve group by ID."""
        try:
            doc = self.db.collection("groups").document(group_id).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error retrieving group {group_id}: {e}")
            raise

    def store_calendar_data(
        self,
        user_id: str,
        calendar_data: Dict[str, Any],
    ) -> None:
        """Store user's calendar availability data."""
        try:
            self.db.collection("calendar_data").document(user_id).set(calendar_data)
            logger.info(f"Calendar data stored for user: {user_id}")
        except Exception as e:
            logger.error(f"Error storing calendar data: {e}")
            raise

    def store_venue_metadata(
        self,
        venue_id: str,
        venue_data: Dict[str, Any],
    ) -> None:
        """Store venue metadata from external APIs."""
        try:
            venue_data["cached_at"] = datetime.utcnow()
            self.db.collection("venues").document(venue_id).set(venue_data)
            logger.info(f"Venue metadata stored: {venue_id}")
        except Exception as e:
            logger.error(f"Error storing venue metadata: {e}")
            raise

    def get_venue(self, venue_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached venue metadata."""
        try:
            doc = self.db.collection("venues").document(venue_id).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error retrieving venue {venue_id}: {e}")
            raise

    def store_vote(self, vote_data: Dict[str, Any]) -> str:
        """
        Store a user's vote on an event option.

        Returns:
            Vote document ID
        """
        try:
            doc_ref = self.db.collection("votes").add(vote_data)
            vote_id = doc_ref[1].id
            logger.info(f"Vote stored: {vote_id}")
            return vote_id
        except Exception as e:
            logger.error(f"Error storing vote: {e}")
            raise

    def get_votes_for_option(self, option_id: str) -> List[Dict[str, Any]]:
        """Retrieve all votes for a specific event option."""
        try:
            docs = (
                self.db.collection("votes")
                .where(
                    "event_option_id",
                    "==",
                    option_id,
                )
                .stream()
            )
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Error retrieving votes for option {option_id}: {e}")
            raise

    def store_event_option(
        self,
        option_data: Dict[str, Any],
    ) -> str:
        """
        Store a generated event option.

        Returns:
            Option document ID
        """
        try:
            doc_ref = self.db.collection("event_options").add(option_data)
            option_id = doc_ref[1].id
            logger.info(f"Event option stored: {option_id}")
            return option_id
        except Exception as e:
            logger.error(f"Error storing event option: {e}")
            raise

    def store_final_event(self, event_data: Dict[str, Any]) -> str:
        """Store a finalized group event."""
        try:
            doc_ref = self.db.collection("events").add(event_data)
            event_id = doc_ref[1].id
            logger.info(f"Final event stored: {event_id}")
            return event_id
        except Exception as e:
            logger.error(f"Error storing final event: {e}")
            raise

    def store_post_event_rating(
        self,
        rating_data: Dict[str, Any],
    ) -> str:
        """Store post-event feedback."""
        try:
            doc_ref = self.db.collection("post_event_ratings").add(rating_data)
            rating_id = doc_ref[1].id
            logger.info(f"Post-event rating stored: {rating_id}")
            return rating_id
        except Exception as e:
            logger.error(f"Error storing post-event rating: {e}")
            raise

    def get_group_feedback_history(self, group_id: str) -> List[Dict[str, Any]]:
        """Retrieve all feedback history for a group."""
        try:
            docs = (
                self.db.collection("post_event_ratings")
                .where(
                    "group_id",
                    "==",
                    group_id,
                )
                .stream()
            )
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Error retrieving feedback for group {group_id}: {e}")
            raise

    def delete_document(self, collection: str, doc_id: str) -> None:
        """Delete a document from a collection."""
        try:
            self.db.collection(collection).document(doc_id).delete()
            logger.info(f"Document deleted: {collection}/{doc_id}")
        except Exception as e:
            logger.error(f"Error deleting document: {e}")
            raise


# Singleton instance
_firestore_client: Optional[FirestoreClient] = None


def get_firestore_client() -> FirestoreClient:
    """Get or create singleton Firestore client."""
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = FirestoreClient()
    return _firestore_client
