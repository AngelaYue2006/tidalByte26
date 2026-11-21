# LifeLine — Product Vision

## One-line pitch

**LifeLine is a Nemotron-powered voice agent that does the phone calls older adults dread, books what they need with one tap, and brings family in only for the part they are needed for.**

## Who it is for

**Primary user:** an older adult who wants to keep running their own appointments without spending a morning on hold. **Secondary participant:** a family member or caregiver the user has chosen as their emergency contact, often living far away. Both see the same dashboard. Either can start a request.

Later: anyone who hates phone calls, people who just moved, people without insurance, non-English speakers.

## The problem

Booking a routine appointment means finding clinics, calling each one, asking the same three questions about insurance, price and openings, comparing the answers against a calendar, calling back, and then arranging a ride. Each step is small. Together they are why appointments get put off, and why an adult child three hours away ends up doing it by phone from work.

## What LifeLine does

1. **Listens once.** The user speaks or types the request on the dashboard.
2. **Keeps private things private.** A local Nemotron Nano model turns the request into the few facts a clinic needs and drops the rest before anything leaves the laptop.
3. **Makes the calls.** Three AI agents phone three nearby clinics at the same time, introduce themselves as an AI assistant calling for a patient, and ask about insurance, price and openings that fit the user's free time.
4. **Decides and explains.** Hard rules in code remove anything over budget, outside free time or not covered. Nemotron Super ranks the rest and shows why: "Fits your free time Thu 9:30", "Cheapest $95 vs $120", "Closest 1.2 mi", plus the trade-off in one sentence.
5. **Asks once.** The user taps Approve, or replies YES to a text. That is the only question LifeLine asks.
6. **Finishes the job.** Books with the clinic, creates a private calendar event with a day-before reminder, checks for a ride, and if no accessible ride exists, texts the emergency contact with exactly what they need to know.
7. **Reports honestly.** Appointment confirmed, ride confirmed, or what is still open. Status comes from verified results, never from what the agent said on the phone.

## Why it is more than a chatbot

- **It talks to real people on the user's behalf** and finishes the task, like TalkTuahBank's phone agent but for care logistics.
- **Privacy is architectural, not a promise.** The sensitive text is processed by an open-weights model on the device. The cloud models and the clinics only ever see the redacted request.
- **Family participation is scoped and two-way.** The contact is asked for one specific thing, can answer by text or on the dashboard, and never sees what the user did not consent to share.
- **Evidence-based status.** Tentative, confirmed and failed are kept apart. A calendar event is never proof of a booking.
- **Low effort by design.** One request, one approval. The agent decides everything else and reports back.

These are emphases the hackathon should prove on test cases, not claims that other assistants cannot do the same.

## Design principles

- **User first:** the user decides what the contact sees; a contact relationship grants nothing by default.
- **Decisions in code, judgment in the model:** budget, calendar and insurance rules are enforced in code; the model ranks and explains within them.
- **Never fabricate certainty:** the agent's spoken words are conversation, not evidence.
- **Verifiable actions:** every status change has an event with a timestamp and a source.
- **No medical judgment:** LifeLine coordinates appointments; it never advises on care.
- **Accessible by design:** one big button, large text, repetition, SMS as a parallel channel.
- **Graceful fallback:** every external service has a mock mode that emits the same events.

## Safety and operational constraints

The agent always discloses that it is an AI. During the hackathon only consenting teammates' phones are called. Transcripts are text only; no audio is recorded. Synthetic identities and insurance details are used throughout. Real clinics may refuse third-party booking; a production version would need legal, privacy and security review, and real identity verification.

## Roadmap (not MVP commitments)

- The user phones LifeLine instead of using the dashboard.
- Auto-approve within user-set rules; rescheduling; reminders that confirm the ride the day before.
- Fine-tuned call agent with before-and-after scores on synthetic receptionist calls.
- Insurance card photo intake; Spanish-language calls; vet, eye exam, haircut, car repair.
- Configurable contact permissions and revocation; audit trail.

## Success definition

A working closed loop on stage: a spoken request, three live transcripts, an explained pick, one tap, a calendar event, a text to the contact, a reply, and an accurate final status. Plus the number that matters: minutes to a booked appointment with LifeLine versus calling the clinics yourself.
