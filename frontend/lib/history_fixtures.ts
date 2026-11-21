// Two seeded past runs — same shape demo/reset will write once the tasks API lands.
// Used when GET /api/tasks fails or ?preview=1.

import type { LiveEvent } from "@/lib/events";
import type { HistoryTask } from "@/lib/history";

export const SEEDED_TASKS: HistoryTask[] = [
  {
    id: "task-seed-2",
    owner_id: "mary",
    status: "completed",
    viewer_role: "owner",
    chips: [
      "Dental cleaning",
      "Max $150",
      "Delta Dental",
      "Free: Tue pm, Thu am",
      "!Processed on device",
    ],
    request_text:
      "“I need a dental cleaning this week, under $150. I have Delta Dental.”",
    booking: {
      clinic: "Bright Smile Dental",
      slot_start: "2026-11-20T09:30:00-06:00",
      slot_end: "2026-11-20T10:00:00-06:00",
      price: "$95",
      status: "confirmed",
      confirmation_ref: "BS-4421",
    },
    transport: {
      available: false,
      reason: "UNAVAILABLE_ACCESSIBLE_RIDE",
      simulated: true,
    },
    decision: { winner_call_id: "a", reasons: ["Lowest price", "In window", "Insured"] },
    created_at: "2026-11-19T14:22:00-06:00",
    updated_at: "2026-11-19T14:28:00-06:00",
  },
  {
    id: "task-seed-1",
    owner_id: "mary",
    status: "completed",
    viewer_role: "owner",
    chips: ["Dental cleaning", "Max $120", "Delta Dental", "!Processed on device"],
    request_text: "“Can you find a cleaning under $120 this week?”",
    booking: {
      clinic: "Smile Co.",
      slot_start: "2026-11-12T15:00:00-06:00",
      slot_end: "2026-11-12T15:30:00-06:00",
      price: "$110",
      status: "confirmed",
      confirmation_ref: "SC-1188",
    },
    transport: {
      available: true,
      reason: "CONTACT_DRIVING",
      simulated: true,
    },
    decision: { winner_call_id: "b", reasons: ["Fits budget", "Afternoon slot"] },
    created_at: "2026-11-11T10:05:00-06:00",
    updated_at: "2026-11-11T10:12:00-06:00",
  },
];

export const SEEDED_EVENTS: Record<string, LiveEvent[]> = {
  "task-seed-2": [
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
    { type: "call_status", call_id: "a", status: "live" },
    {
      type: "transcript",
      call_id: "a",
      speaker: "agent",
      text: "Hi, I'm an AI assistant calling for a patient. Do you take Delta Dental?",
    },
    {
      type: "transcript",
      call_id: "a",
      speaker: "clinic",
      text: "Yes we do. We have Thursday at 9:30 for $95.",
    },
    {
      type: "call_result",
      call_id: "a",
      price: "$95",
      slot: "Thu 9:30",
      insured: true,
      slotOk: true,
    },
    {
      type: "decision",
      winner: "a",
      title: "Bright Smile Dental · Thu 9:30 · $95",
      reasons: ["Lowest price", "In window", "Insured"],
      second: ["1.2 mi"],
      tradeoff: "Smile Co. was closer but $25 more.",
    },
    {
      type: "approved",
      by: "mary",
      via: "dashboard",
    },
    {
      type: "booked",
      calendar: "Thu 9:30 · Bright Smile Dental",
      sms_user: "Booked Bright Smile Dental Thu 9:30 for $95.",
    },
    {
      type: "transport_check",
      status: "unavailable",
      reason: "UNAVAILABLE_ACCESSIBLE_RIDE",
      simulated: true,
    },
    {
      type: "notified",
      sms_contact:
        "Mary has a cleaning Thu 9:30 at Bright Smile Dental. Can you drive?",
    },
  ],
  "task-seed-1": [
    {
      type: "request",
      text: "“Can you find a cleaning under $120 this week?”",
      chips: ["Dental cleaning", "Max $120", "Delta Dental", "!Processed on device"],
    },
    { type: "call_start", call_id: "b", clinic: "Smile Co.", meta: "0.6 mi" },
    {
      type: "transcript",
      call_id: "b",
      speaker: "agent",
      text: "Hi, I'm an AI assistant. Any cleanings under $120 this week?",
    },
    {
      type: "transcript",
      call_id: "b",
      speaker: "clinic",
      text: "Wednesday at 3 for $110 with Delta Dental.",
    },
    {
      type: "call_result",
      call_id: "b",
      price: "$110",
      slot: "Wed 3:00",
      insured: true,
      slotOk: true,
    },
    {
      type: "decision",
      winner: "b",
      title: "Smile Co. · Wed 3:00 · $110",
      reasons: ["Fits budget", "Afternoon slot"],
      second: ["0.6 mi"],
      tradeoff: "Only one offer under $120.",
    },
    {
      type: "booked",
      calendar: "Wed 3:00 · Smile Co.",
      sms_user: "Booked Smile Co. Wed 3:00 for $110.",
    },
    {
      type: "transport_check",
      status: "available",
      reason: "CONTACT_DRIVING",
      simulated: true,
    },
  ],
};
