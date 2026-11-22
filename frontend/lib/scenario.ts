// Prototype SCENARIO events (no timing / audio) for reducer tests.
// Source: frontend/prototype/index.html — do not edit the prototype for this.

import type { LiveEvent } from "@/lib/events";

export const PROTOTYPE_SCENARIO: LiveEvent[] = [
  {
    type: "request",
    text: "“I need a dental cleaning this week, under $150. I have Delta Dental.”",
    chips: [
      "Dental cleaning",
      "Max $150",
      "Delta Dental",
      "Free: Tue pm, Thu am",
      "!Processed on device",
    ],
  },
  { type: "call_start", call_id: "a", clinic: "Bright Smile Dental", meta: "1.2 mi" },
  { type: "call_start", call_id: "b", clinic: "Smile Co.", meta: "0.6 mi" },
  { type: "call_start", call_id: "c", clinic: "Oak Dental", meta: "3.4 mi" },
  { type: "call_status", call_id: "a", status: "live" },
  { type: "call_status", call_id: "b", status: "live" },
  { type: "call_status", call_id: "c", status: "hold" },
  {
    type: "transcript",
    call_id: "a",
    speaker: "agent",
    text: "Hi, I'm an AI assistant calling for a patient. Do you take Delta Dental?",
  },
  {
    type: "transcript",
    call_id: "b",
    speaker: "agent",
    text: "Hi, I'm an AI assistant calling for a patient. Any cleanings open this week?",
  },
  {
    type: "transcript",
    call_id: "c",
    speaker: "clinic",
    text: "Thanks for calling Oak Dental, please hold…",
  },
  {
    type: "transcript",
    call_id: "a",
    speaker: "clinic",
    text: "Yes, we do. A cleaning is $95 with Delta.",
  },
  {
    type: "transcript",
    call_id: "b",
    speaker: "clinic",
    text: "Our next opening is Friday at 4. It's $120 with Delta.",
  },
  {
    type: "transcript",
    call_id: "a",
    speaker: "agent",
    text: "Great. Anything Tuesday afternoon or Thursday morning?",
  },
  {
    type: "transcript",
    call_id: "b",
    speaker: "agent",
    text: "Thanks, I'll check with the patient and call back.",
  },
  {
    type: "call_result",
    call_id: "b",
    price: "$120",
    slot: "Fri 4:00",
    insured: true,
    slotOk: false,
  },
  { type: "call_status", call_id: "b", status: "done" },
  {
    type: "transcript",
    call_id: "a",
    speaker: "clinic",
    text: "Thursday at 9:30 is open.",
  },
  {
    type: "transcript",
    call_id: "a",
    speaker: "agent",
    text: "Perfect, please hold that for Mary Johnson. Thank you!",
  },
  {
    type: "call_result",
    call_id: "a",
    price: "$95",
    slot: "Thu 9:30",
    insured: true,
    slotOk: true,
  },
  { type: "call_status", call_id: "a", status: "done" },
  { type: "call_status", call_id: "c", status: "live" },
  {
    type: "transcript",
    call_id: "c",
    speaker: "clinic",
    text: "Sorry for the wait. We're $140, earliest is next Monday.",
  },
  {
    type: "call_result",
    call_id: "c",
    price: "$140",
    slot: "Mon 10:00",
    insured: true,
    slotOk: false,
  },
  { type: "call_status", call_id: "c", status: "done" },
  {
    type: "decision",
    winner: "a",
    title: "Why Nemotron picked Bright Smile Dental",
    reasons: [
      "Fits your free time · Thu 9:30",
      "Cheapest · $95 vs $120, $140",
      "Takes Delta Dental",
    ],
    second: ["2nd closest · 1.2 mi"],
    tradeoff:
      "Trade-off: Smile Co. is closer (0.6 mi), but its only opening is Friday at 4, when your calendar is busy.",
  },
  {
    type: "booked",
    sms_user:
      "AIGranni: Booked Bright Smile Dental, Thu Nov 26, 9:30 AM, $95 with Delta. Reply C to cancel.",
    calendar:
      "<b>Appointment</b><br><span class='muted'>Thu Nov 26 · 9:30–10:30 AM<br>123 Main St · private · reminder 1 day before</span>",
  },
  {
    type: "notified",
    sms_contact:
      "AIGranni: Appointment booked for Mary — Bright Smile Dental, Thu Nov 26 at 9:30 AM, 123 Main St.",
  },
];
