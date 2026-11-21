# LifeLine — Product Vision

## One-line pitch

**LifeLine is a Nemotron-powered, phone-first personal advocate that helps older adults coordinate essential tasks independently, while involving trusted family members only when needed and authorized.**

**Tagline:** One call for everyday help. Independence for you, peace of mind for your family.

## Who is it for?

**Initial user:** older adults or people facing digital-accessibility barriers who want to remain in control of routine administration. **Secondary participant:** a user-authorized family member or trusted supporter. Later audiences include people with language, mobility or digital-literacy barriers.

Avoid assuming all older adults dislike technology or need a caregiver. Design for varied abilities, preferences and consent choices.

## The problem

An apparently simple goal—such as attending an eye appointment—can mean coordinating provider calls, calendar availability, mobility accommodations, transport, confirmation and changes. Interfaces are fragmented; services require repeated follow-up; family may live far away and can become the default coordinator. Generic AI assistants may automate actions, but the distinctive unmet need LifeLine targets is **accessible, reliable multi-party coordination that protects user preferences and autonomy**.

## Core value proposition

The user calls one number and states a goal. LifeLine:

1. Extracts hard constraints and softer preferences.
2. Plans dependent tasks and uses authorized tools.
3. Negotiates alternatives and recovers from failures.
4. Verifies external results before declaring completion.
5. With explicit consent, requests specific assistance from the right trusted contact.
6. Reports status and unresolved items in accessible language.

**Collaborative independence:** AI handles repetitive coordination; the user remains the decision-maker; family helps only for authorized, specific needs.

## Representative journey

A grandparent calls to request an eye appointment next week, excluding Tuesday and preferring mornings. Nemotron checks the connected calendar and gets a suitable slot from a **simulated** clinic. Transport with required accessibility accommodations cannot be arranged. With pre-granted permission for transport-related outreach, LifeLine sends an SMS to the daughter's verified number. She offers a ride. The workflow requests user confirmation when policy requires, records the arrangement and communicates an accurate final status.

## What's different from general assistants?

- **Phone-native access** with an alternative for users unable to use voice; no new smartphone app required for the primary interaction.
- **Constraint-aware advocacy** with protected hard constraints and explicit tradeoffs for soft preferences.
- **Multi-party workflow** including authorized family participation, not just one-user automation.
- **Dependency-aware execution** (appointment changes trigger transport revalidation).
- **Evidence-based status** separating requested, tentative, confirmed, and verified actions.
- **Measurable safeguards** for privacy, approvals, and recovery.

These are deliberate product emphases, **not claims that Muse, Hermes or other assistants cannot implement similar features**. The hackathon should prove the difference on test cases rather than assert exclusivity.

## Cross-disciplinary impact

AI agents + scheduling/optimization + accessible HCI + gerontology and family caregiving + privacy/security engineering + service operations. Real-world impact hypotheses: fewer abandoned tasks, reduced administrative burden and appropriate family involvement. **Do not claim validated health or independence outcomes from a hackathon prototype.**

## Design principles

- **User first:** contact relationships do not create default data access; user decides what is shared.
- **Least privilege:** separate viewing, helping, and action approval permissions.
- **Never fabricate certainty:** distinguish proposed, tentative, confirmed and failed actions.
- **Verifiable actions:** keep evidence and timestamps for status transitions.
- **Approvals in code:** the model can propose a step; software enforces permissions and authorization.
- **No medical judgment:** coordinate administrative tasks, never diagnose or change treatment.
- **Accessible by design:** repetition, slower speech, concise confirmation, optional keypad/text or human assistance.
- **Graceful fallback:** state survives dropped calls and tool failures; explain what remains unresolved.

## Safety and operational constraints

Real providers may require direct identity verification and may refuse third-party booking. Disclose AI identity as appropriate; comply with applicable telephone, recording and messaging consent requirements. A real production healthcare or financial use case requires legal/privacy/security assessment, vendor agreements where applicable, and robust authentication. The demo uses **synthetic identities and simulated clinic/transport systems**, and never represents a calendar entry alone as proof of provider confirmation. Keep secrets out of logs and repos.

## Longer-term roadmap (not MVP commitments)

- Configurable family roles, sharing and revocation; caregiver-assisted enrollment.
- Multi-provider and real transport adapters; delayed follow-up and rescheduling.
- Multilingual and alternate interface channels.
- Document-to-action workflows (letters and notices); optional link to CareBridge concept.
- Insurance, home maintenance and public-service coordination after legal/product validation.

## Open questions to validate after hackathon

- Do target users prefer a landline call, mobile call, SMS, or mixed interface?
- How should first-time identity proofing and calendar linkage work without excluding users?
- Who pays for calls, voice inference, and external services?
- Which details do users actually want family to see, and when?
- What percentage of providers permit AI booking; when must the user join the call?
- Can we demonstrate meaningful reliability gains versus a fixed script?

## Success definition

For the hackathon, success means a clear, working **one-scenario closed loop** that respects constraints, coordinates a real authorized family reply, verifies the simulated appointment and ride, and shows exactly how Nemotron adapts when something changes. Nothing beyond that is necessary to prove the product hypothesis.
