from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
from typing import Any, Dict, List, Text
import logging

logger = logging.getLogger(__name__)


class ActionSetDialogPath(Action):
    """
    Called immediately after the user chooses recommendation vs. direct booking.
    Sets the dialog_path slot so downstream actions (and your analysis) know
    which branch was taken.
    """

    def name(self) -> Text:
        return "action_set_dialog_path"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        last_intent = tracker.latest_message.get("intent", {}).get("name")

        if last_intent == "want_recommendation":
            path = "recommendation"
        elif last_intent == "want_booking":
            path = "direct_booking"
        else:
            path = "direct_booking"  # safe fallback

        logger.info(f"Dialog path set to: {path}")
        return [SlotSet("dialog_path", path)]


class ActionGiveRecommendations(Action):
    """
    Returns a list of restaurant recommendations based on district + cuisine slots.
    Replace the stub list with a real lookup (DB, API, etc.) when ready.
    """

    def name(self) -> Text:
        return "action_give_recommendations"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        district = tracker.get_slot("district") or "your area"
        cuisine = tracker.get_slot("cuisine") or "various cuisines"

        # --- STUB: replace with real restaurant data ---
        recommendations = [
            "Restaurant Alpha",
            "Restaurant Beta",
            "Restaurant Gamma",
        ]
        # ------------------------------------------------

        rec_list = ", ".join(recommendations)
        dispatcher.utter_message(
            text=(
                f"Here are some {cuisine} restaurants in {district}: "
                f"{rec_list}. Would you like to book one of these?"
            )
        )

        # Pre-fill restaurant_name with first suggestion as default;
        # overwritten if user specifies one explicitly.
        return [SlotSet("restaurant_name", recommendations[0])]


class ActionHandleBooking(Action):
    """
    Final booking action. Checks system_version slot to decide whether to
    complete smoothly (System A) or inject a planned difficulty (System B).

    System B difficulty is injected HERE, not scattered through stories,
    so it stays in one place and is easy to adjust for your study.

    dialog_path is also logged here for your IQ analysis pipeline.
    """

    def name(self) -> Text:
        return "action_handle_booking"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        system_version = tracker.get_slot("system_version")  # "A" or "B"
        dialog_path = tracker.get_slot("dialog_path")        # "recommendation" or "direct_booking"
        restaurant = tracker.get_slot("restaurant_name")
        date = tracker.get_slot("date")
        time = tracker.get_slot("time")
        num_people = tracker.get_slot("num_people")

        logger.info(
            f"Booking attempt | system={system_version} | path={dialog_path} | "
            f"restaurant={restaurant} | date={date} | time={time} | people={num_people}"
        )

        if system_version == "B" and dialog_path == "direct_booking":
            # -------------------------------------------------------
            # SYSTEM B DIFFICULTY INJECTION — direct booking path
            # The flag logic you described: difficulty only fires when
            # the user skipped the recommendation path.
            #
            # TODO: choose your difficulty type, e.g.:
            #   - Slot reset (force user to re-enter date)
            #   - ASR-style misunderstanding ("Did you say Tuesday?")
            #   - Confirmation loop that fails once before succeeding
            # -------------------------------------------------------
            dispatcher.utter_message(
                text="I'm sorry, I couldn't find that restaurant in our system. "
                     "Could you double-check the name?"
            )
            # Reset restaurant slot to force re-entry
            return [SlotSet("restaurant_name", None)]

        elif system_version == "B" and dialog_path == "recommendation":
            # -------------------------------------------------------
            # SYSTEM B DIFFICULTY INJECTION — recommendation path
            # Milder difficulty (or none) since user followed the
            # guided flow. Adjust to match your study design.
            # -------------------------------------------------------
            dispatcher.utter_message(
                text=f"To confirm: {restaurant} on {date} at {time} "
                     f"for {num_people} people — shall I go ahead?"
            )
            return []

        else:
            # System A — smooth confirmation, no friction
            dispatcher.utter_message(
                text=f"To confirm: {restaurant} on {date} at {time} "
                     f"for {num_people} people — shall I go ahead?"
            )
            return []
