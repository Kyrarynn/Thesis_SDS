from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet

# Placeholder restaurant data. Replace with a real lookup later
# (e.g. a small fixed list per condition, or a JSON/Mongo lookup).
RESTAURANTS_BY_CUISINE = {
    "italian": "Trattoria Bella",
    "japanese": "Sakura Sushi",
    "greek": "Olive Taverna",
    "indian": "Spice Route",
    "mexican": "Casa Verde",
    "thai": "Lotus Thai",
    "chinese": "Golden Dragon",
}

DEFAULT_RESTAURANT = "The Garden Bistro"


class ActionRecommendRestaurant(Action):
    """Looks up a restaurant suggestion based on the cuisine slot.

    This is where you would later inject the induced difficulty for
    System Version A (e.g. delay, wrong recommendation, or a forced
    clarification loop) since the recommendation step happens early
    in the conversation.
    """

    def name(self) -> Text:
        return "action_recommend_restaurant"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        cuisine = (tracker.get_slot("cuisine") or "").lower()
        restaurant = RESTAURANTS_BY_CUISINE.get(cuisine, DEFAULT_RESTAURANT)

        dispatcher.utter_message(
            text=f"I'd recommend {restaurant} for {cuisine or 'that'} food."
        )

        return [SlotSet("restaurant_choice", restaurant)]


class ActionConfirmBooking(Action):
    """Finalizes the booking.

    This is where you would later inject the induced difficulty for
    System Version B (e.g. a failed booking attempt, a request to
    repeat information, or an unavailable time slot) since this step
    happens near the end of the conversation.
    """

    def name(self) -> Text:
        return "action_confirm_booking"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        # Placeholder: in the real study, log this event (with a
        # timestamp and session/condition ID) to MongoDB from here
        # or, more simply, from the FastAPI orchestrator that calls
        # Rasa, so all logging logic stays in one place.
        return []
