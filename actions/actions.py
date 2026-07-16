
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, FollowupAction
from rasa_sdk.forms import FormValidationAction
from rasa_sdk.types import DomainDict
from typing import Any, Dict, List, Text
import logging

logger = logging.getLogger(__name__)

# ============================================================
# Conversation Start
# ============================================================

class ChooseYourPath(Action):
    def name(self) -> Text:
        return "choose_your_path"

    def run(self, dispatcher, tracker, domain):
        
        dispatcher.utter_message(response="utter_greet")
        dispatcher.utter_message(response="utter_ask_path")

        path = tracker.get_slot("dialog_path")

        if (path == "recommendation"):

            # log path 
            FollowupAction("start_direct_booking")
        
        elif (path == "direct_booking"):

            # log path
            FollowupAction("start_recommendation")

        else:
            dispatcher.utter_message(response="utter_ask_path_again")  

        



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
    # Accept entity value if extracted, otherwise use raw text as fallback
        if slot_value:
            return {"food_preference": slot_value}
        # Check raw text for "no preference" type responses
        text = tracker.latest_message.get("text", "").lower()
        no_pref_keywords = ["no preference", "don't care", "no", "not really", "none"]
        if any(kw in text for kw in no_pref_keywords):
            return {"food_preference": "none"}
        dispatcher.utter_message(text="I didn't catch that. Do you have any dietary preferences, or no preference?")
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

    def name(self) -> Text:
        return "action_give_recommendations"

    def run(self, dispatcher, tracker, domain):
        district = tracker.get_slot("district") or "your area"
        cuisine = tracker.get_slot("cuisine") or "various cuisines"
        food_preference = tracker.get_slot("food_preference") or ""

        # TO_DO — replace with real data
        recommendations = [
            "Alpha Mouse Cheese Palace",
            "Beta Test - Food Creation",
            "Gamma Grandma Cooking",
        ]

        pref_str = f" {food_preference}" if food_preference and food_preference != "none" else ""
        rec_list = "\n".join([f"  {i+1}. {r}" for i, r in enumerate(recommendations)])

        dispatcher.utter_message(
            text=(
                f"Here are some{pref_str} {cuisine} restaurants in {district}:\n"
                f"{rec_list}\n"
                f"Which one would you like? You can say the name or the number."
            )
        )

        # Stores recommendations in a slot so the choice action can look them up
        return [SlotSet("recommendations", recommendations)]


class ActionHandleRecommendationChoice(Action):

    def name(self) -> Text:
        return "action_handle_recommendation_choice"

    def run(self, dispatcher, tracker, domain):
        recommendations = tracker.get_slot("recommendations") or []
        text = tracker.latest_message.get("text", "").lower()

        chosen = None

        # Try to match by number ("1", "option 1", "the first one")
        number_map = {
            "1": 0, "one": 0, "first": 0, "a": 0,
            "2": 1, "two": 1, "second": 1, "b": 1,
            "3": 2, "three": 2, "third": 2, "c": 2,
        }
        for keyword, index in number_map.items():
            if keyword in text and index < len(recommendations):
                chosen = recommendations[index]
                break

        # Try to match by name directly
        if not chosen:
            for rec in recommendations:
                if rec.lower() in text:
                    chosen = rec
                    break

        # Fallback to first option
        if not chosen and recommendations:
            chosen = recommendations[0]

        logger.info(f"Recommendation chosen: {chosen}")
        return [SlotSet("restaurant_name", chosen)]

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