
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
from rasa_sdk.forms import FormValidationAction
from rasa_sdk.types import DomainDict
from typing import Any, Dict, List, Text
import logging

logger = logging.getLogger(__name__)


# ============================================================
# FORM VALIDATORS
# ============================================================

class ValidateRecommendationForm(FormValidationAction):
    """
    Validates all slots during the recommendation form.
    """

    def name(self) -> Text:
        return "validate_recommendation_form"

    def validate_district(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        if slot_value and len(slot_value.strip()) > 1:
            return {"district": slot_value.strip()}
        dispatcher.utter_message(text="I didn't catch the district. Which area are you looking in?")
        return {"district": None}

    def validate_cuisine(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        if slot_value and len(slot_value.strip()) > 1:
            return {"cuisine": slot_value.strip()}
        dispatcher.utter_message(text="I didn't catch that. What kind of food are you in the mood for?")
        return {"cuisine": None}
    
    def validate_food_preference(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        if slot_value and len(slot_value.strip()) > 1:
            return {"food_preference": slot_value.strip()}
        dispatcher.utter_message(text="Sorry, could you repeat that? What kind of food preference do you have?")
        return {"food_preference": None}


class ValidateBookingForm(FormValidationAction):
    """
    Validates all four booking slots.
    """

    def name(self) -> Text:
        return "validate_booking_form"

    def validate_restaurant_name(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        if slot_value and len(slot_value.strip()) > 1:
            return {"restaurant_name": slot_value.strip()}
        dispatcher.utter_message(text="I didn't catch the restaurant name. Could you say it again?")
        return {"restaurant_name": None}

    def validate_date(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        if slot_value:
            return {"date": slot_value}
        dispatcher.utter_message(text="I didn't catch the date. Could you repeat it?")
        return {"date": None}

    def validate_time(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        if slot_value:
            return {"time": slot_value}
        dispatcher.utter_message(text="I didn't catch the time. Could you say it again?")
        return {"time": None}

    def validate_num_people(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        try:
            n = int(slot_value)
            if 1 <= n <= 6:
                return {"num_people": n}
            dispatcher.utter_message(text="Please enter a number between 1 and 6.")
            return {"num_people": None}
        except (ValueError, TypeError):
            dispatcher.utter_message(text="I need a number for the party size. How many people?")
            return {"num_people": None}


# ============================================================
# CUSTOM ACTIONS
# ============================================================

class ActionSetDialogPath(Action):
    """
    Fires immediately after the user chooses a path.
    Sets dialog_path slot for downstream logic and IQ analysis.
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

        if last_intent == "choose_recommendation_path":
            path = "recommendation"
        elif last_intent == "choose_own_restaurant":
            path = "direct_booking"
        else:
            path = "direct_booking"  # safe fallback

        logger.info(f"Dialog path set to: {path}")
        return [SlotSet("dialog_path", path)]


class ActionGiveRecommendations(Action):
    """
    Returns restaurant recommendations based on district + cuisine.
    TODO: replace stub list with real data source.
    """

    def name(self) -> Text:
        return "action_give_recommendations"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        district = tracker.get_slot("district") or "Mitte"
        cuisine = tracker.get_slot("cuisine") or "Japanese"
        food_preference = tracker.get_slot("food_preference") or "Vegan"

        # --- STUB: replace with real restaurant data ---
        recommendations = [
            "Alpha Mouse Cheese Palace",
            "Beta Test - Food Creation",
            "Gamma Grandma Cooking",
        ]
        # -----------------------------------------------

        rec_list = ", ".join(recommendations)
        dispatcher.utter_message(
            text=(
                f"Here are some {food_preference} {cuisine} restaurants in {district}: "
                f"{rec_list}. Which one would you like?"
            )
        )

        return []


class ActionConfirmRestaurantName(Action):
    """
    Handles restaurant name collection and confirmation loop for direct booking path.

    Turn 1: restaurant_name is empty → ask for name
    Turn 2: restaurant_name is filled, not yet confirmed → ask for confirmation
    Turn 3a: user affirms → rule moves to booking_form
    Turn 3b: user denies → clear slot, ask again (back to Turn 1)

    TODO: System B difficulty injection here (e.g. forced misrecognition,
    re-entry loop) when dialog_path == "direct_booking".
    """

    def name(self) -> Text:
        return "action_confirm_restaurant_name"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        awaiting_confirmation = tracker.get_slot("awaiting_restaurant_confirmation")
        last_intent = tracker.latest_message.get("intent", {}).get("name")

        if awaiting_confirmation and last_intent == "deny":
            # User said the name was wrong — clear and ask again
            dispatcher.utter_message(text="My apologies! What is the correct restaurant name?")
            return [
                SlotSet("restaurant_name", None),
                SlotSet("awaiting_restaurant_confirmation", False),
            ]

        restaurant_name = tracker.get_slot("restaurant_name")

        if not restaurant_name:
            # Slot not yet filled — ask for name
            dispatcher.utter_message(text="Which restaurant would you like to book?")
            return [SlotSet("awaiting_restaurant_confirmation", False)]

        # Name is filled — ask for confirmation
        dispatcher.utter_message(
            text=f"You want to eat at {restaurant_name}, is that correct?"
        )
        return [SlotSet("awaiting_restaurant_confirmation", True)]


class ActionHandleBooking(Action):
    """
    Final booking step. Reads system_version and dialog_path to decide
    whether to confirm smoothly (System A) or inject difficulty (System B).

    Difficulty injection is centralised here — one place to control
    for both paths, making it easy to adjust for your study design.
    """

    def name(self) -> Text:
        return "action_handle_booking"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        system_version = tracker.get_slot("system_version")
        dialog_path    = tracker.get_slot("dialog_path")
        restaurant     = tracker.get_slot("restaurant_name")
        date           = tracker.get_slot("date")
        time           = tracker.get_slot("time")
        num_people     = tracker.get_slot("num_people")

        logger.info(
            f"Booking | system={system_version} | path={dialog_path} | "
            f"restaurant={restaurant} | date={date} | time={time} | people={num_people}"
        )

        if system_version == "B" and dialog_path == "direct_booking":
            # -------------------------------------------------------
            # SYSTEM B — direct booking path difficulty injection
            # TODO: define exact difficulty type, e.g.:
            #   - Forced name re-entry ("Sorry, I can't find that restaurant")
            #   - ASR misrecognition ("Did you say Tuesday?")
            #   - Confirmation loop failure (ask twice before accepting)
            # -------------------------------------------------------
            dispatcher.utter_message(
                text="I'm sorry, I couldn't find that restaurant in our system. "
                     "Could you double-check the name?"
            )
            return [SlotSet("restaurant_name", None)]

        elif system_version == "B" and dialog_path == "recommendation":
            # -------------------------------------------------------
            # SYSTEM B — recommendation path difficulty injection
            # Milder friction or none — adjust to your study design
            # -------------------------------------------------------
            dispatcher.utter_message(
                text=f"To confirm: {restaurant} on {date} at {time} "
                     f"for {num_people} people — shall I go ahead?"
            )
            return []

        else:
            # System A — smooth confirmation
            dispatcher.utter_message(
                text=f"To confirm: {restaurant} on {date} at {time} "
                     f"for {num_people} people — shall I go ahead?"
            )
            return []