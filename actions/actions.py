from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, SessionStarted, ActionExecuted
from rasa_sdk.forms import FormValidationAction
from rasa_sdk.types import DomainDict
from typing import Any, Dict, List, Text

import re
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

        # Standard session start events. NOTE: action_listen must be the LAST
        # event (see end of this method). If a SlotSet comes after it, a
        # fallback on the participant's very first utterance reverts it
        # (UserUtteranceReverted rewinds up to the previous action_listen),
        # and system_version silently becomes None for the whole session.
        events = [SessionStarted()]

        # -------------------------------------------------------
        # TEMPORARY — hardcoded for testing, remove before study
        """ 
        system_version = "B"  # switch to "A" / "B" to test the other system 
        events.append(SlotSet("system_version", system_version))
        logger.info(f"Session started | system_version={system_version} [HARDCODED]")
        """
        
        # Read system_version from metadata passed by FastAPI
        """ 
        metadata = tracker.get_slot("session_started_metadata") or {}
        """
        # Rasa puts the request metadata into this slot before running
        # action_session_start; fall back to the metadata of the last user event
        # (the explicit "/session_start" message sent by FastAPI).
        metadata = tracker.get_slot("session_started_metadata") or {}
        if not metadata.get("system_version"):
            last_user_event = tracker.get_last_event_for("user")
            metadata = (last_user_event or {}).get("metadata") or {}

        system_version = metadata.get("system_version")

        if system_version in ("A", "B"):
            events.append(SlotSet("system_version", system_version))
            logger.info(f"Session started | system_version={system_version}")
        else:
            logger.warning(
                f"No valid system_version in session metadata: {metadata}. "
                f"Error injection will not fire."
            )

        events.append(ActionExecuted("action_listen"))   # must stay last
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

def get_system_version(tracker: Tracker):
    """System version of this session: the slot, or (if the slot was lost)
    the last SlotSet(system_version) in the event history of this session."""
    v = tracker.get_slot("system_version")
    if v in ("A", "B"):
        return v
    for e in reversed(tracker.events):
        if e.get("event") == "session_started":
            break
        if e.get("event") == "slot" and e.get("name") == "system_version" and e.get("value") in ("A", "B"):
            logger.warning(f"system_version slot was empty, recovered {e['value']!r} from history "
                           f"(sender={tracker.sender_id})")
            return e["value"]
    logger.warning(f"system_version missing! sender={tracker.sender_id}")
    return None


def a_error_already_fired(tracker: Tracker) -> bool:
    """True if the System A error was already shown in this session.
    Read from the event history, because the error_fired slot is reset
    to False after the participant's correction."""
    for e in reversed(tracker.events):
        if e.get("event") == "session_started":
            return False
        if e.get("event") == "slot" and e.get("name") == "error_fired" and e.get("value") is True:
            return True
    return False


def slots_set_this_turn(tracker: Tracker) -> Dict[Text, Any]:
    """Slots that were set after the latest user message (slot extraction)."""
    slots: Dict[Text, Any] = {}
    for e in reversed(tracker.events):
        if e.get("event") == "user":
            break
        if e.get("event") == "slot" and e.get("name") not in slots:
            slots[e["name"]] = e.get("value")
    return slots


class RevalidateAfterUnhappyPathMixin:
    """Rasa skips slot validation on the first form run after an unhappy path
    (e.g. after action_handle_form_fallback): the form is called with
    LoopInterrupted(True) and slots_to_validate() is empty, so the slot that
    was just extracted (e.g. food_preference="vegan") is accepted unvalidated
    -> the System A error never fires. Here we validate such slots ourselves."""

    async def run(self, dispatcher, tracker, domain):
        events = await super().run(dispatcher, tracker, domain)
        validated = tracker.slots_to_validate()
        required = await self.required_slots(
            self.domain_slots(domain), dispatcher, tracker, domain
        )
        for slot, value in slots_set_this_turn(tracker).items():
            if slot not in required or slot in validated or value is None:
                continue
            validate = getattr(self, f"validate_{slot}", None)
            if validate is None:
                continue
            logger.info(f"Re-validating {slot}={value!r} skipped by Rasa (form returned from unhappy path)")
            result = validate(value, dispatcher, tracker, domain)
            events.extend(SlotSet(k, v) for k, v in (result or {}).items())
        return events


# reset function
class ActionResetAfterBooking(Action):
    def name(self) -> Text:
        return "action_reset_after_booking"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("awaiting_booking_confirmation", False)]

# ============================================================
# DISTRICT MATCHING
# ============================================================
# Whisper often splits German district names into English words
# ("Charlottenburg" -> "Charlotte, Hamburg", "Spandau" -> "Span Dow").
# The NLU entity then only covers a fragment ("Hamburg"). We therefore match
# against the FULL user utterance and only accept real Berlin districts.

import unicodedata
from difflib import SequenceMatcher

DISTRICT_ALIASES = {
    "Mitte": ["mitteh", "mitta", "mitter", "mita", "mitti"],
    "Friedrichshain": ["friedrichschain", "friedrichshein", "freedrichshain", "friedrichshayn", "fredrichshain", "friedrichshine"],
    "Kreuzberg": ["kroytzberg", "kroitzberg", "kreutzberg", "kreuzburg", "croyzberg"],
    "Prenzlauer Berg": ["prenzlowerberg", "prenzlaurberg", "prentslauerberg", "prenslauerberg", "prenzlauerburg", "prenzlberg"],
    "Pankow": ["pankov", "pankoff", "pankau"],
    "Charlottenburg": ["charlottenberg", "charlottenbourg", "charlottenbug", "charlottenburgh", "charlottesburg",
                       "charlottehamburg", "charlotteburg", "charlotteandburg", "charlotteinburg"],
    "Wilmersdorf": ["wilmersdorff", "wilmersdorg"],
    "Spandau": ["spandow", "spando", "spanndau", "spandao", "spandaw", "spundau", "spundow", "spandou"],
    "Steglitz": ["steaglitz", "steeglitz", "steglits", "stegliz"],
    "Tempelhof": ["tempelhoff", "tempelhove", "templhof", "templehof"],
    "Schöneberg": ["schoneberg", "shoneberg", "shoeneberg", "schoeneburg", "schoneburg", "shonaberg"],
    "Neukölln": ["neukoln", "neukolln", "neucoln", "noykeln", "noykolln"],
    "Treptow": ["treptau", "treptov", "treptoe"],
    "Köpenick": ["kopenick", "koepenik", "kopenik"],
    "Marzahn": ["marzan", "marzaan", "martzahn"],
    "Hellersdorf": ["hellersdorff"],
    "Lichtenberg": ["lichtenbourg", "lichtenbug", "lichtenberk", "lichtenburg"],
    "Reinickendorf": ["reinickendorff", "reinickendorg", "rhinickendorf", "reinikendorf"],
    "Hoppegarten": ["hoppegarden", "hoppagarten"],
}


def _norm_text(s: Text) -> Text:
    """lowercase, umlauts -> ae/oe/ue, drop everything that is not a letter"""
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s)


_DISTRICT_KEYS = (
    sorted(((_norm_text(d), d) for d in DISTRICT_ALIASES), key=lambda x: -len(x[0]))
    + sorted(((a, d) for d, al in DISTRICT_ALIASES.items() for a in al), key=lambda x: -len(x[0]))
)


def match_district(*texts: Text):
    """Return the canonical Berlin district found in any of the texts, else None."""
    norm = [_norm_text(t) for t in texts if t]
    # 1) exact name or known variant anywhere in the utterance (longest keys first)
    for t in norm:
        for key, district in _DISTRICT_KEYS:
            if key in t:
                return district
    # 2) fuzzy fallback; stricter for short names (avoids "Spandow" -> "Pankow")
    best, best_score = None, 0.0
    for t in norm:
        for key, district in _DISTRICT_KEYS:
            n = len(key)
            need = 0.9 if n <= 7 else 0.82
            if len(t) < n - 2:
                continue
            for w in range(max(1, n - 2), n + 3):
                for i in range(0, max(1, len(t) - w + 1)):
                    score = SequenceMatcher(None, key, t[i:i + w]).ratio()
                    if score >= need and score > best_score:
                        best, best_score = district, score
    return best

# ============================================================
# TIME / PARTY SIZE PARSING
# ============================================================
# The time and num_people slots are filled from the raw text while the booking
# form asks for them (see domain.yml). These helpers turn Whisper output such as
# "6 p.m.", "Six PM.", "at 6", "half past seven" into a clean value.

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


def _words_to_digits(t: Text) -> Text:
    return re.sub(r"\b(" + "|".join(_NUM_WORDS) + r")\b",
                  lambda m: str(_NUM_WORDS[m.group(1)]), t)


def parse_time(text: Text):
    """Return a time like '6 pm' / '7:30 pm', or None if the text contains no time."""
    if not text:
        return None
    t = text.lower()
    t = re.sub(r"\bp\.?\s?m\b\.?", " pm", t)      # p.m. / p. m. / pm
    t = re.sub(r"\ba\.?\s?m\b\.?", " am", t)      # a.m.
    t = t.replace("o'clock", " oclock").replace("o clock", " oclock")
    t = _words_to_digits(t)

    hour = minute = None
    ampm = None
    m = re.search(r"half past (\d{1,2})", t)
    if m:
        hour, minute = int(m.group(1)), 30
    if hour is None:
        m = re.search(r"quarter past (\d{1,2})", t)
        if m:
            hour, minute = int(m.group(1)), 15
    if hour is None:
        m = re.search(r"quarter to (\d{1,2})", t)
        if m:
            hour, minute = int(m.group(1)) - 1, 45
    if hour is None:
        # prefer a number that is followed by pm/am/oclock
        m = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*(pm|am|oclock)\b", t)
        if not m:
            m = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\b", t)
        if not m:
            return None
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
    if re.search(r"\bam\b", t):
        ampm = "am"
    if re.search(r"\bpm\b", t):
        ampm = "pm"

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if hour > 12:                       # 18:00 -> 6 pm
        hour, ampm = hour - 12, "pm"
    elif hour == 0:
        hour, ampm = 12, "am"
    elif ampm is None:                  # restaurant booking: "at 6" means 6 pm
        ampm = "pm"
    return f"{hour}:{minute:02d} {ampm}" if minute else f"{hour} {ampm}"


def parse_party_size(text: Text):
    """Return the number of people (1-20) in the text, or None."""
    if not text:
        return None
    t = text.lower()
    if re.search(r"\b(just me|only me|myself|alone)\b", t):
        return 1
    t = _words_to_digits(t)
    m = re.search(r"\b(\d{1,2})\b", t)
    if m and 1 <= int(m.group(1)) <= 20:
        return int(m.group(1))
    return None

# ============================================================
# FORM VALIDATORS
# ============================================================

class ValidateRecommendationForm(RevalidateAfterUnhappyPathMixin, FormValidationAction):
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
        # Check the full utterance first: the entity may only hold a fragment
        # ("Charlotte, Hamburg" -> entity "Hamburg").
        user_text = tracker.latest_message.get("text", "")
        district = match_district(user_text, slot_value or "")
        if district:
            if district != slot_value:
                logger.info(f"District normalised: entity={slot_value!r} text={user_text!r} -> {district}")
            return {"district": district}
        logger.info(f"District rejected: entity={slot_value!r} text={user_text!r}")
        # Short message only: the form asks utter_ask_district again right after this.
        dispatcher.utter_message(text="Sorry, I didn't catch the district.")
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

        system_version = get_system_version(tracker)
        error_fired = a_error_already_fired(tracker)

        # Check if no preference -> intent == deny (happens when user says "no" or something similar)
        last_intent = tracker.latest_message.get("intent", {}).get("name")
        if last_intent == "deny":
            return {"food_preference": "none", "error_fired": False}

        # -------------------------------------------------------
        # SYSTEM A ERROR — misunderstands food preference once
        # The error only fires on the first attempt (error_fired=False)
        # so the dialog recovers naturally on the second try.
        # -------------------------------------------------------
        logger.info(f"FoodPref | system={system_version} | error_already_fired={error_fired} "
                    f"| value={slot_value!r} | text={get_last_user_text(tracker)!r}")
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



class ValidateBookingForm(RevalidateAfterUnhappyPathMixin, FormValidationAction):
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
        # slot_value is the raw user text (from_text mapping while the time is asked)
        user_text = tracker.latest_message.get("text", "") or str(slot_value or "")
        parsed = parse_time(user_text) or parse_time(str(slot_value or ""))
        if parsed:
            logger.info(f"Time parsed: text={user_text!r} -> {parsed}")
            return {"time": parsed}
        logger.info(f"Time rejected: text={user_text!r}")
        dispatcher.utter_message(text="Sorry, I didn't catch the time.")
        return {"time": None}

    def validate_num_people(
    self,
    slot_value: Any,
    dispatcher: CollectingDispatcher,
    tracker: Tracker,
    domain: DomainDict,
    ) -> Dict[Text, Any]:
        # slot_value is the raw user text or the entity; check the full utterance
        user_text = tracker.latest_message.get("text", "") or str(slot_value or "")
        n = parse_party_size(user_text) or parse_party_size(str(slot_value or ""))
        if n:
            return {"num_people": n}
        logger.info(f"Party size rejected: text={user_text!r}")
        dispatcher.utter_message(text="Sorry, I need a number between 1 and 20.")
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

        # Match by restaurant name directly first — most specific
        for rec in recommendations:
            if rec.lower() in text:
                chosen = rec
                break

        # Then match by ordinal/number — check more specific terms first
        if not chosen:
            # to avoid "one" in "second one" matching index 0
            ordered_map = [
                (["3", "three", "third", "c"], 2),
                (["2", "two", "second", "b"], 1),
                (["1", "first", "a"],         0),
            ]
            words = re.sub(r'[^\w\s]', '', text).split()
            for keywords, index in ordered_map:
                if any(kw in words for kw in keywords) and index < len(recommendations):
                    chosen = recommendations[index]
                    break

        # Fallback to first only if nothing matched
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

        system_version = get_system_version(tracker)
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