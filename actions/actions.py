from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, SessionStarted, ActionExecuted
from rasa_sdk.forms import FormValidationAction
from rasa_sdk.types import DomainDict
from typing import Any, Dict, List, Text

import logging

logger = logging.getLogger(__name__)



class ActionSessionStart(Action):
    """
    Fires at the start of every conversation.
    Reads system_version from session metadata sent by FastAPI
    and sets it as a slot so the rest of the dialog can use it.
    
    FastAPI sends the metadata in the session start payload:
    {
        "sender": "participant_123",
        "session_metadata": {"system_version": "A"}
    }
    """

    # ============================================================
    # Override action session start function
    # ============================================================

    def name(self) -> Text:
        return "action_session_start"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        # Standard session start events — always required
        events = [SessionStarted(), ActionExecuted("action_listen")]

        # -------------------------------------------------------
        # TEMPORARY — hardcoded for testing, remove before study
        """ 
        system_version = "B"  # switch to "A" / "B" to test the other system 
        events.append(SlotSet("system_version", system_version))
        logger.info(f"Session started | system_version={system_version} [HARDCODED]")
        """
        # de-comment """ for fastAPI

        """ 
        """
        # Read system_version from metadata passed by FastAPI
        metadata = tracker.get_slot("session_started_metadata") or {}
        system_version = metadata.get("system_version")

        if system_version in ("A", "B"):
            events.append(SlotSet("system_version", system_version))
            logger.info(f"Session started | system_version={system_version}")
        else:
            logger.warning(
                f"No valid system_version in session metadata: {metadata}. "
                f"Error injection will not fire."
            )

        return events

# ============================================================
# HELPER
# ============================================================
 
def get_last_user_text(tracker: Tracker) -> str:
    """
    Reliably retrieves the most recent user message text from the
    event history. More robust than tracker.latest_message inside
    form validation calls where message context can be ambiguous.
    """
    for event in reversed(tracker.events):
        if event.get("event") == "user":
            return event.get("text", "").strip()
    return ""

# reset function
class ActionResetAfterBooking(Action):
    def name(self) -> Text:
        return "action_reset_after_booking"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("awaiting_booking_confirmation", False)]

# ============================================================
# FORM VALIDATORS
# ============================================================

class ValidateRecommendationForm(FormValidationAction):
    """
    Validates district, cuisine, and food_preference slots.

    SYSTEM A ERROR — fires on food_preference slot.
    Simulates an ASR misrecognition: the system mishears the dietary
    preference and repeats back a plausible wrong value, forcing the
    user to correct it. Error fires exactly once then resolves.
    """

    def name(self) -> Text:
        return "validate_recommendation_form"

    def validate_district(self, slot_value, dispatcher, tracker, domain):
    # slot_value is now always the raw text (from_text mapping)
        if slot_value:
            cleaned = slot_value.strip()
            for prefix in ["i'm looking in ", "in ", "at ", "near ", "around "]:
                if cleaned.lower().startswith(prefix):
                    cleaned = cleaned[len(prefix):]
                    break
            if len(cleaned) > 1:
                return {"district": cleaned.strip()}
        dispatcher.utter_message(
            text="I didn't catch the district. Which area are you looking in?"
        )
        return {"district": None}

    def validate_cuisine(self, slot_value, dispatcher, tracker, domain):
        if slot_value:
            cleaned = slot_value.strip()
            # Strip common filler phrases
            for prefix in ["i want ", "i'd like ", "i feel like ", "something "]:
                if cleaned.lower().startswith(prefix):
                    cleaned = cleaned[len(prefix):]
                    break
            if len(cleaned) > 1:
                return {"cuisine": cleaned.strip()}
        dispatcher.utter_message(
            text="I didn't catch that. What kind of food are you in the mood for?"
        )
        return {"cuisine": None}

    def validate_food_preference(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:

        system_version = tracker.get_slot("system_version")
        error_fired = tracker.get_slot("error_fired")

        # Check if no preference -> intent == deny (happens when user says "no" or something similar)
        last_intent = tracker.latest_message.get("intent", {}).get("name")
        if last_intent == "deny":
            return {"food_preference": "none", "error_fired": False}

        # -------------------------------------------------------
        # SYSTEM A ERROR — misunderstands food preference once
        # The error only fires on the first attempt (error_fired=False)
        # so the dialog recovers naturally on the second try.
        # -------------------------------------------------------
        if system_version == "A" and not error_fired:
            raw = get_last_user_text(tracker)
            # Generate a plausible mishearing based on what the user said
            mishearing_map = {
                "vegan": "began",
                "vegetarian": "Mediterranean",
                "halal": "falafel",
                "gluten free": "gluten three",
                "gluten": "glutton",
            }
            raw_lower = raw.lower()
            mishearing = next(
                (v for k, v in mishearing_map.items() if k in raw_lower),
                "begin"   # generic fallback mishearing
            )
            dispatcher.utter_message(
                text=f'I\'m sorry, did you say "{mishearing}"? '
                     f"I didn't quite catch that. "
                     f"Could you repeat your dietary preference?"
            )
            return {"food_preference": None, "error_fired": True}
 
        # Normal validation — entity extraction or raw text fallback
        if slot_value:
            return {"food_preference": slot_value, "error_fired": False}
 
        raw = get_last_user_text(tracker).lower()
        no_pref_keywords = ["no preference", "don't care", "no", "not really", "none", "nothing"]
        if any(kw in raw for kw in no_pref_keywords):
            return {"food_preference": "none", "error_fired": False}
 
        dispatcher.utter_message(
            text="I didn't catch that. Do you have any dietary preferences, "
                 "or no preference?"
        )
        return {"food_preference": None}



class ValidateBookingForm(FormValidationAction):
    """
    Validates date, time, and num_people slots.
    Uses raw text fallback for date and time since these are
    free-text expressions rather than structured entities.
    """

    def name(self) -> Text:
        return "validate_booking_form"

    def validate_date(
    self,
    slot_value: Any,
    dispatcher: CollectingDispatcher,
    tracker: Tracker,
    domain: DomainDict,
    ) -> Dict[Text, Any]:
        if slot_value:
            return {"date": slot_value}
        for event in reversed(tracker.events):
            if event.get("event") == "user":
                raw_text = event.get("text", "").strip()
                if raw_text:
                    return {"date": raw_text}
        dispatcher.utter_message(text="I didn't catch the date. Could you repeat it?")
        return {"date": None}

    def validate_time(self, slot_value, dispatcher, tracker, domain):
        if slot_value:
            return {"time": slot_value}
        raw = get_last_user_text(tracker)
        if raw:
            # Basic sanity check — reject obvious nonsense
            time_hints = [":", "am", "pm", "o'clock", "half", "quarter",
                        "morning", "afternoon", "evening", "night",
                        "one", "two", "three", "four", "five", "six",
                        "seven", "eight", "nine", "ten", "eleven", "twelve"]
            if any(hint in raw.lower() for hint in time_hints) or any(c.isdigit() for c in raw):
                return {"time": raw}
            dispatcher.utter_message(
                text="I didn't quite understand that time. "
                    "Could you say it again? For example: 7pm, half past six, 19:00."
            )
            return {"time": None}
        dispatcher.utter_message(text="I didn't catch the time. Could you say it again?")
        return {"time": None}

    def validate_num_people(
    self,
    slot_value: Any,
    dispatcher: CollectingDispatcher,
    tracker: Tracker,
    domain: DomainDict,
    ) -> Dict[Text, Any]:

        word_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
            "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
            "nineteen": 19, "twenty": 20,
        }

        # Get the value to parse — entity extraction or raw text fallback
        raw = slot_value
        if not raw:
            for event in reversed(tracker.events):
                if event.get("event") == "user":
                    raw = event.get("text", "").strip().lower()
                    break

        if not raw:
            dispatcher.utter_message(text="I need a number for the party size. How many people?")
            return {"num_people": None}

        # Try word first, then digit
        raw_lower = str(raw).lower().strip()
        if raw_lower in word_to_num:
            return {"num_people": word_to_num[raw_lower]}

        try:
            n = int(raw_lower)
            if 1 <= n <= 20:
                return {"num_people": n}
            dispatcher.utter_message(text="Please enter a number between 1 and 20.")
            return {"num_people": None}
        except (ValueError, TypeError):
            dispatcher.utter_message(text="I need a number for the party size. How many people?")
            return {"num_people": None}

# ============================================================
# CUSTOM ACTIONS
# ============================================================

class ActionGiveRecommendations(Action):
    """
    Returns a numbered list of restaurants based on filled slots.
    Stores the list in the recommendations slot for later resolution.
    TODO: replace stub list with real data source.
    """

    # Normalisation map: STT variants → correct display name
    DISTRICT_NORMALISE = {
        # Mitte
        "mitteh": "Mitte",
        "mitta": "Mitte",
        # Friedrichshain
        "friedrichshein": "Friedrichshain",
        "friedrichschain": "Friedrichshain",
        "friedrichs hain": "Friedrichshain",
        "freedrichshain": "Friedrichshain",
        "friedrichshayn": "Friedrichshain",
        # Charlottenburg
        "charlottenberg": "Charlottenburg",
        "charlottenbourg": "Charlottenburg",
        "charlottenbug": "Charlottenburg",
        # Wilmersdorf
        "wilmersdorff": "Wilmersdorf",
        "wilmers dorf": "Wilmersdorf",
        "wilmersdorg": "Wilmersdorf",
        # Neukölln
        "neukoelln": "Neukölln",
        "neu köln": "Neukölln",
        "neuköln": "Neukölln",
        "neu coln": "Neukölln",
        "noykeln": "Neukölln",
        # Steglitz
        "steaglitz": "Steglitz",
        "steeglitz": "Steglitz",
        "steglits": "Steglitz",
        # Spandau
        "spandow": "Spandau",
        "spando": "Spandau",
        "spanndau": "Spandau",
        # Prenzlauer Berg
        "prenzlower berg": "Prenzlauer Berg",
        "prenzlaur berg": "Prenzlauer Berg",
        "prentslauer berg": "Prenzlauer Berg",
        "prenslauer berg": "Prenzlauer Berg",
        # Tempelhof
        "tempelhoff": "Tempelhof",
        "tempelhove": "Tempelhof",
        "templ hof": "Tempelhof",
        # Lichtenberg
        "lichtenbourg": "Lichtenberg",
        "lichtenbug": "Lichtenberg",
        "lichtenberk": "Lichtenberg",
        # Marzahn
        "marzan": "Marzahn",
        "marzaan": "Marzahn",
        "mar zahn": "Marzahn",
        # Treptow
        "treptau": "Treptow",
        "treptov": "Treptow",
        "trep tow": "Treptow",
        # Reinickendorf
        "reinickendorff": "Reinickendorf",
        "reinickendorg": "Reinickendorf",
        "rein ickendorf": "Reinickendorf",
        "rhinickendorf": "Reinickendorf",
        # Schöneberg
        "schoeneberg": "Schöneberg",
        "shoneberg": "Schöneberg",
        "schoneberg": "Schöneberg",
        "shoeneberg": "Schöneberg",
        # Kreuzberg
        "kroytzberg": "Kreuzberg",
        "kroitzberg": "Kreuzberg",
        "kreutzberg": "Kreuzberg",
        "kreuzburg": "Kreuzberg",
        # Pankow
        "pankov": "Pankow",
        "pankoff": "Pankow",
        "pan kow": "Pankow",
        # Hoppegarten
        "hoppegarden": "Hoppegarten",
        "hoppe garten": "Hoppegarten",
        "hoppa garten": "Hoppegarten",
    }

    # recommendations per cuisine - hardcoded for reproducability
    RESTAURANT_RECOMMENDATIONS = {
    "italian": [
        "Trattoria da Lorenzo",
        "La Piazza Verde",
        "Ristorante Bellavista",
    ],
    "german": [
        "Zum Goldenen Bären",
        "Die Alte Schmiede",
        "Gasthaus Waldeck",
    ],
    "japanese": [
        "Sakura Garden",
        "Ramen Yoshi",
        "Sushi Matsuri",
    ],
    "thai": [
        "Bangkok Garden",
        "Lotus Thai Kitchen",
        "Sabai Sabai",
    ],
    "chinese": [
        "Golden Dragon",
        "Dim Sum House",
        "Panda Garden",
    ],
    "indian": [
        "Spice Garden",
        "Bombay Dreams",
        "Curry House Berlin",
    ],
    "mexican": [
        "Casa Guadalupe",
        "El Sombrero",
        "La Cantina",
    ],
    "greek": [
        "Olympia",
        "Mykonos Restaurant",
        "Acropolis Grill",
    ],
}

    def name(self) -> Text:
        return "action_give_recommendations"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        district_raw = tracker.get_slot("district") or "your area"
        cuisine = tracker.get_slot("cuisine") or "various cuisines"
        food_preference = tracker.get_slot("food_preference") or ""

        # Normalise district display name
        district = self.DISTRICT_NORMALISE.get(district_raw.lower(), district_raw)

        # Look up restaurants by cuisine, fall back to generic list
        cuisine_key = cuisine.lower()
        all_options = self.RESTAURANT_RECOMMENDATIONS.get(
            cuisine_key,
            ["Restaurant Aurora", "Bistro Central", "Café Metropol"]  # generic fallback
        )

        # Always show exactly 3
        recommendations = all_options[:3]

        pref_str = f" {food_preference}" if food_preference and food_preference != "none" else ""
        rec_list = "\n".join([f"  {i+1}. {r}" for i, r in enumerate(recommendations)])

        dispatcher.utter_message(
            text=(
                f"Here are some{pref_str} {cuisine} restaurants in {district}:\n"
                f"{rec_list}\n"
                f"Which one would you like? You can say the name or the number of the option you want to choose."
            )
        )

        return [
            SlotSet("recommendations", recommendations),
            SlotSet("awaiting_restaurant_choice", True),
        ]


class ActionHandleRecommendationChoice(Action):
    """
    Resolves the user's restaurant choice from the recommendations list.
    Sets restaurant_name and asks for confirmation before starting the
    booking form.
    """

    def name(self) -> Text:
        return "action_handle_recommendation_choice"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        recommendations = tracker.get_slot("recommendations") or []
        text = tracker.latest_message.get("text", "").lower()

        chosen = None

        # Match by number or ordinal word
        number_map = {
            "1": 0, "one": 0, "first": 0, "a": 0,
            "2": 1, "two": 1, "second": 1, "b": 1,
            "3": 2, "three": 2, "third": 2, "c": 2,
        }
        for keyword, index in number_map.items():
            if keyword in text.split() and index < len(recommendations):
                chosen = recommendations[index]
                break

        # Match by restaurant name directly
        if not chosen:
            for rec in recommendations:
                if rec.lower() in text:
                    chosen = rec
                    break

        # Fallback to first option
        if not chosen and recommendations:
            chosen = recommendations[0]

        logger.info(f"Recommendation chosen: {chosen}")

        dispatcher.utter_message(
            text=f"Great choice! You've selected {chosen}. Shall I go ahead and book a table there?"
        )

        return [
            SlotSet("restaurant_name", chosen),
            SlotSet("awaiting_booking_start", True),
            SlotSet("awaiting_restaurant_choice", False),
        ]


class ActionHandleBooking(Action):
    """
    Final booking step. Presents a summary and asks for confirmation.

    SYSTEM B ERROR — fires here, near the end of the dialog.
    Simulates a slot confirmation failure: the system claims it cannot
    process the date and asks the user to re-enter it. This creates a
    realistic late-dialog frustration event close to the Peak-End 'end'.
    The error fires exactly once then resolves on the next attempt.

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
        error_fired    = tracker.get_slot("error_fired")
        restaurant     = tracker.get_slot("restaurant_name")
        date           = tracker.get_slot("date")
        time           = tracker.get_slot("time")
        num_people     = tracker.get_slot("num_people")

        logger.info(
            f"Booking | system={system_version} | restaurant={restaurant} | "
            f"date={date} | time={time} | people={num_people} | error_fired={error_fired}"
        )

        # -------------------------------------------------------
        # SYSTEM B ERROR — simulated date parsing failure
        #
        # Fires on the first booking attempt only.
        # The system presents the full summary correctly, then claims
        # it cannot process the date and asks the user to re-confirm
        # it. This is realistic — date parsing failures are common in
        # real SDS — and hits late in the dialog, close to the 'end'
        # component of the Peak-End Rule.
        # Resolves cleanly on the second attempt.
        # -------------------------------------------------------
        if system_version == "B" and not error_fired:
            dispatcher.utter_message(
                text=f"I have {restaurant} on {date} at {time} "
                     f"for {num_people} people. "
                     f"However, I'm having trouble processing the date \"{date}\". "
                     f"Could you confirm the date once more?"
            )
            return [
                SlotSet("awaiting_booking_start", False),
                SlotSet("date", None),
                SlotSet("awaiting_booking_confirmation", True),
                SlotSet("error_fired", True),
            ]
 
        # Normal confirmation — System A and System B after error resolves
        dispatcher.utter_message(
            text=f"To confirm: {restaurant} on {date} at {time} "
                 f"for {num_people} people — shall I go ahead?"
        )
        return [
            SlotSet("awaiting_booking_start", False),
            SlotSet("error_fired", False),
            SlotSet("awaiting_booking_confirmation", True)
        ]


class ActionHandleFormFallback(Action):
    """
    Fires when the user says something unrecognised while a form is active.
    Re-prompts for the current slot without breaking the form loop.
    """

    def name(self) -> Text:
        return "action_handle_form_fallback"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        requested_slot = tracker.get_slot("requested_slot")

        reprompts = {
            "district": "I didn't understand that. Which district are you looking in? "
                        "For example: Mitte, Kreuzberg, or Prenzlauer Berg.",
            "cuisine":  "I didn't catch that cuisine. What kind of food are you in the mood for? "
                        "For example: Italian, Japanese, or German.",
            "food_preference": "I didn't understand that preference. "
                               "You can say vegan, vegetarian, halal, gluten free, or no preference.",
            "date":     "I didn't catch that date. Could you say it again? "
                        "For example: next Monday, or the 15th of September.",
            "time":     "I didn't catch that time. Could you say it again? "
                        "For example: 7pm, half past six, or 19:00.",
            "num_people": "I need a number for the party size. "
                          "How many people will be dining?",
        }

        message = reprompts.get(
            requested_slot,
            "I didn't understand that. Could you rephrase?"
        )
        dispatcher.utter_message(text=message)
        return []