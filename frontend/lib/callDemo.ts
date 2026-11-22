import type { DentalPreferences } from "./demoIntake";

export const clinics = [
  { name: "Bright Smile Dental", price: 95, slot: "Thursday at 9:30", delay: 0, alternate: false },
  { name: "Smile Co.", price: 120, slot: "Friday at 4", delay: 1, alternate: true },
  { name: "Oak Dental", price: 140, slot: "Monday at 10", delay: 2, alternate: false },
];

export type Step = "connect" | "coverage" | "time" | "alternate" | "offer";
export type Turn = { at: number; speaker: "AI assistant" | "Receptionist"; text: string; step?: Step };

export function script(clinic: typeof clinics[number], budget?: number | null): Turn[] {
  if (clinic.name === "Oak Dental") return [
    { at: 3, speaker: "AI assistant", step: "connect", text: "Hi, I'm an AI assistant calling for a patient. May I check your cleaning appointments?" },
    { at: 7, speaker: "Receptionist", text: "We just had a cancellation on Monday." },
    { at: 11, speaker: "AI assistant", step: "time", text: "What time is the Monday opening?" },
    { at: 16, speaker: "Receptionist", text: "Monday at 10 in the morning." },
    { at: 21, speaker: "AI assistant", step: "coverage", text: "I'll check the cost next. What would a cleaning cost with Delta Dental?" },
    { at: 26, speaker: "Receptionist", text: "We take Delta Dental. The cleaning would be $140." },
    { at: 31, speaker: "AI assistant", step: "offer", text: "I'll share Monday at 10 for $140 with the patient. Thank you." },
  ];
  const turns: Turn[] = [
    { at: 3, speaker: "AI assistant", step: "connect", text: "Hi, I'm an AI assistant calling for a patient. May I ask about a dental cleaning?" },
    { at: 7, speaker: "Receptionist", text: "Of course. Which insurance plan would you like me to check?" },
    { at: 11, speaker: "AI assistant", step: "coverage", text: "Let’s check coverage first. Do you accept Delta Dental, and what would the cleaning cost?" },
    { at: 16, speaker: "Receptionist", text: clinic.alternate
      ? 'We accept Delta Dental. A cleaning is $120, but our Thursday morning slots are full.'
      : `Yes, we accept Delta Dental. The cleaning would be $${clinic.price}.` },
    { at: 21, speaker: "AI assistant", step: clinic.alternate ? "alternate" : "time", text: clinic.alternate
      ? "Since Thursday is full, I’ll ask about another day. What else is available?"
      : typeof budget === "number" && clinic.price > budget ? "That exceeds the patient’s budget. What time was that quote for?" : "Thank you. I’ll check availability next. When could the patient come in?" },
    { at: 26, speaker: "Receptionist", text: `We have an opening on ${clinic.slot}.` },
    { at: 31, speaker: "AI assistant", step: "offer", text: `I’ll share ${clinic.slot} at $${clinic.price} with the patient for review. Thank you!` },
  ];
  return turns;
}

export function callStatus(age: number) {
  if (age < 1) return "Planned";
  if (age < 3) return "Ringing";
  if (age < 35) return "Calling";
  return "Finished";
}

export const demoEnd = 35 + Math.max(...clinics.map(clinic => clinic.delay));
export function timestamp(second: number) {
  return `0:${String(second).padStart(2, "0")}`;
}


export const stepLabels: Record<Step, string> = {
  connect: "Introduce AI", coverage: "Check coverage", time: "Ask for a time",
  alternate: "Find another day", offer: "Report offer",
};

export type DemoRun = { started: number; pausedAt: number | null; approved: boolean; preferences?: DentalPreferences };
const storageKey = "lifeline:simulated-cleaning:v1";
export function readDemoRun(): DemoRun | null {
  try {
    const run = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    return run && Number.isFinite(run.started) && typeof run.approved === "boolean" &&
      (run.pausedAt === null || Number.isFinite(run.pausedAt)) ? run : null;
  } catch { return null; }
}
export function saveDemoRun(run: DemoRun | null) {
  try {
    if (run) sessionStorage.setItem(storageKey, JSON.stringify(run));
    else sessionStorage.removeItem(storageKey);
  } catch { /* Playback still works in memory when browser storage is unavailable. */ }
}
export function elapsedSeconds(run: DemoRun, now = Date.now()) {
  return Math.min(demoEnd, Math.max(0, Math.floor(((run.pausedAt ?? now) - run.started) / 1000)));
}

const archiveKey = "lifeline:reviewed-demo:v1";
export function archiveDemo(approved: boolean, preferences?: DentalPreferences) {
  try {
    sessionStorage.setItem(archiveKey + ":preferences", JSON.stringify(preferences ?? {}));
    sessionStorage.setItem(archiveKey, approved || sessionStorage.getItem(archiveKey) === "approved" ? "approved" : "review");
  } catch { /* Optional tab-local demo history. */ }
}
export function demoArchive() {
  try { return sessionStorage.getItem(archiveKey); } catch { return null; }
}

export function archivedBudget(): number | undefined {
  try {
    const value = JSON.parse(sessionStorage.getItem(archiveKey + ":preferences") ?? "{}").budget;
    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
  } catch { return undefined; }
}
