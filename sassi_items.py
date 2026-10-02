"""
SASSI – Subjective Assessment of Speech System Interfaces
Hone, K. S. & Graham, R. (2000). Towards a tool for the subjective assessment
of speech system interfaces (SASSI). Natural Language Engineering, 6(3-4), 287-303.

34 items, 6 subscales, 7-point agreement scale.

Coding of raw answers:
    1 = strongly disagree ... 4 = neutral ... 7 = strongly agree

Scoring convention used here: HIGHER SCORE = MORE POSITIVE for every subscale.
Items marked reverse=True are recoded as (8 - answer) before averaging.
Note for interpretation:
    - Annoyance: all items are negatively worded, so a high score means
      LOW annoyance.
    - Cognitive Demand: a high score means LOW demand (user felt calm/confident).
    - Habitability: a high score means users knew what to say / where they were.
If you prefer the original orientation (e.g. high Annoyance = more annoyed),
simply use 8 - score for that subscale in your analysis.
"""

SCALE_LABELS = [
    "Strongly disagree",
    "Disagree",
    "Slightly disagree",
    "Neutral",
    "Slightly agree",
    "Agree",
    "Strongly agree",
]  # index 0 -> value 1, index 6 -> value 7

SUBSCALES = {
    "ACC": "System Response Accuracy",
    "LIK": "Likeability",
    "CD": "Cognitive Demand",
    "ANN": "Annoyance",
    "HAB": "Habitability",
    "SPD": "Speed",
}

# (item_id, text, reverse)
ITEMS = [
    # System Response Accuracy (9)
    ("ACC1", "The system is accurate", False),
    ("ACC2", "The system is unreliable", True),
    ("ACC3", "The interaction with the system is unpredictable", True),
    ("ACC4", "The system didn't always do what I wanted", True),
    ("ACC5", "The system didn't always do what I expected", True),
    ("ACC6", "The system is dependable", False),
    ("ACC7", "The system makes few errors", False),
    ("ACC8", "The interaction with the system is consistent", False),
    ("ACC9", "The interaction with the system is efficient", False),
    # Likeability (9)
    ("LIK1", "The system is useful", False),
    ("LIK2", "The system is pleasant", False),
    ("LIK3", "The system is friendly", False),
    ("LIK4", "I was able to recover easily from errors", False),
    ("LIK5", "I enjoyed using the system", False),
    ("LIK6", "It is clear how to speak to the system", False),
    ("LIK7", "It is easy to learn to use the system", False),
    ("LIK8", "I would use this system", False),
    ("LIK9", "I felt in control of the interaction with the system", False),
    # Cognitive Demand (5)
    ("CD1", "I felt confident using the system", False),
    ("CD2", "I felt tense using the system", True),
    ("CD3", "I felt calm using the system", False),
    ("CD4", "A high level of concentration is required when using the system", True),
    ("CD5", "The system is easy to use", False),
    # Annoyance (5)
    ("ANN1", "The interaction with the system is repetitive", True),
    ("ANN2", "The interaction with the system is boring", True),
    ("ANN3", "The interaction with the system is irritating", True),
    ("ANN4", "The interaction with the system is frustrating", True),
    ("ANN5", "The system is too inflexible", True),
    # Habitability (4)
    ("HAB1", "I sometimes wondered if I was using the right word", True),
    ("HAB2", "I always knew what to say to the system", False),
    ("HAB3", "I was not always sure what the system was doing", True),
    ("HAB4", "It is easy to lose track of where you are in an interaction with the system", True),
    # Speed (2)
    ("SPD1", "The interaction with the system is fast", False),
    ("SPD2", "The system responds too slowly", True),
]

ITEM_IDS = [i[0] for i in ITEMS]
REVERSE = {i[0]: i[2] for i in ITEMS}


def score(responses: dict[str, int]) -> dict[str, float]:
    """Return mean score per subscale (1-7, higher = more positive)."""
    result = {}
    for prefix in SUBSCALES:
        values = []
        for item_id in ITEM_IDS:
            if item_id.startswith(prefix) and item_id[len(prefix):].isdigit():
                v = responses[item_id]
                values.append(8 - v if REVERSE[item_id] else v)
        result[prefix] = round(sum(values) / len(values), 4)
    # Overall mean across all 34 recoded items
    all_vals = [8 - responses[i] if REVERSE[i] else responses[i] for i in ITEM_IDS]
    result["TOTAL"] = round(sum(all_vals) / len(all_vals), 4)
    return result
