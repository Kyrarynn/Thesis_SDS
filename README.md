# Restaurant Booking SDS – Starter Project

A minimal Rasa project for the restaurant reservation task. This covers
step 1 of the build plan: a working text-only conversation flow, testable
entirely from the terminal, with no frontend, audio, or database yet.

## Setup

```bash
python -m venv venv
source venv/bin/activate          # on Windows: venv\Scripts\activate
pip install rasa rasa-sdk
```

## Train and test

```bash
cd rasa_restaurant_bot
rasa train
rasa shell
```

Try a full booking conversation, e.g.:
- "hi"
- "Italian food sounds good"
- "4 people"
- "7pm"
- "yes, book the table"
- "bye"

## Run the action server (needed for the custom actions)

In a second terminal:

```bash
rasa run actions
```

Then run `rasa shell` again so the custom actions
(`action_recommend_restaurant`, `action_confirm_booking`) are reachable.

## What's deliberately left out for now

- **No frontend** — once `rasa shell` works end-to-end, the next step is a
  minimal FastAPI service that calls Rasa's REST endpoint
  (`http://localhost:5005/webhooks/rest/webhook`), and a small Vue page
  that talks to that FastAPI service.
- **No audio (ASR/TTS)** — add this only after the text loop works through
  the Vue/FastAPI layer.
- **No MongoDB logging** — add this in the FastAPI orchestrator, not in
  Rasa itself, so you have full control over the schema (turn text,
  timestamps, condition/session IDs, ratings, audio file paths).
- **No rating UI, no System A/B difficulty variants, no condition
  assignment** — these come after the basic pipeline (text → audio → Vue
  UI) is solid.

## Where to inject the induced difficulties later

- **System Version A** (difficulty early): inside `action_recommend_restaurant`
  in `actions/actions.py` — e.g. recommend the wrong cuisine, ask a
  redundant clarifying question, or add an artificial delay.
- **System Version B** (difficulty late): inside `action_confirm_booking`
  in `actions/actions.py` — e.g. report the time slot as unavailable and
  require a second confirmation step.

A clean way to implement this without duplicating the whole project: add an
environment variable or a slot (e.g. `system_version`) set at the start of
each session by the FastAPI orchestrator, and branch inside these two
actions based on its value.
