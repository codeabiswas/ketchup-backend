"""Firestore client wrapper for optional pipeline storage paths."""

import logging
from datetime import datetime
from typing import Any, Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)


class FirestoreClient:
    """Thin Firestore wrapper used by pipeline jobs."""

    def __init__(self):
        # Keep imports local so core backend startup does not require pipeline deps.
        from google.cloud import firestore
        from google.oauth2 import service_account

        settings = get_settings()
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

    def create_user(self, user_data: dict[str, Any]) -> str:
        try:
            doc_ref = self.db.collection("users").add(user_data)
            user_id = doc_ref[1].id
            logger.info(f"User created: {user_id}")
            return user_id
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            raise

    def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        """Retrieve user by ID."""
        try:
            doc = self.db.collection("users").document(user_id).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error retrieving user {user_id}: {e}")
            raise

    def get_all_users(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Retrieve all users, optionally filtered to active users only."""
        try:
            query = self.db.collection("users")
            if active_only:
                query = query.where("active", "==", True)

            docs = query.stream()
            users: list[dict[str, Any]] = []
            for doc in docs:
                user = doc.to_dict()
                user.setdefault("user_id", doc.id)
                users.append(user)

            return users
        except Exception as e:
            logger.error(f"Error retrieving users: {e}")
            raise

    def update_user_preferences(
        self,
        user_id: str,
        preferences: dict[str, Any],
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

    def create_group(self, group_data: dict[str, Any]) -> str:
        try:
            doc_ref = self.db.collection("groups").add(group_data)
            group_id = doc_ref[1].id
            logger.info(f"Group created: {group_id}")
            return group_id
        except Exception as e:
            logger.error(f"Error creating group: {e}")
            raise

    def get_group(self, group_id: str) -> Optional[dict[str, Any]]:
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
        calendar_data: dict[str, Any],
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
        venue_data: dict[str, Any],
    ) -> None:
        """Store venue metadata from external APIs."""
        try:
            venue_data["cached_at"] = datetime.utcnow()
            self.db.collection("venues").document(venue_id).set(venue_data)
            logger.info(f"Venue metadata stored: {venue_id}")
        except Exception as e:
            logger.error(f"Error storing venue metadata: {e}")
            raise

    def get_venue(self, venue_id: str) -> Optional[dict[str, Any]]:
        """Retrieve cached venue metadata."""
        try:
            doc = self.db.collection("venues").document(venue_id).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error retrieving venue {venue_id}: {e}")
            raise

    def store_vote(self, vote_data: dict[str, Any]) -> str:
        try:
            doc_ref = self.db.collection("votes").add(vote_data)
            vote_id = doc_ref[1].id
            logger.info(f"Vote stored: {vote_id}")
            return vote_id
        except Exception as e:
            logger.error(f"Error storing vote: {e}")
            raise

    def get_votes_for_option(self, option_id: str) -> list[dict[str, Any]]:
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
        option_data: dict[str, Any],
    ) -> str:
        try:
            doc_ref = self.db.collection("event_options").add(option_data)
            option_id = doc_ref[1].id
            logger.info(f"Event option stored: {option_id}")
            return option_id
        except Exception as e:
            logger.error(f"Error storing event option: {e}")
            raise

    def store_final_event(self, event_data: dict[str, Any]) -> str:
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
        rating_data: dict[str, Any],
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

    def get_group_feedback_history(self, group_id: str) -> list[dict[str, Any]]:
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
