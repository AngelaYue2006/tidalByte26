export type DentalPreferences = { budget?: number | null; ride?: boolean };
export type IntakeField = keyof DentalPreferences;

export function knownPreferences(text: string): DentalPreferences {
  const preferences: DentalPreferences = {};
  const amount = text.match(/(?:under|below|up to|budget(?: of)?|maximum(?: of)?|max|spend)\s*\$?\s*(\d[\d,]*(?:\.\d{1,2})?)\b/i);
  if (amount) preferences.budget = Number(amount[1].replaceAll(",", ""));
  else if (/\b(no budget limit|no maximum|no limit)\b/i.test(text)) preferences.budget = null;
  if (/\b(no ride|(?:don.t|do not) need a ride|(?:have|arrange) my own ride|drive myself)\b/i.test(text)) preferences.ride = false;
  else if (/\b(?:need|want)(?:s)? (?:a ride|transportation)\b/i.test(text)) preferences.ride = true;
  return preferences;
}

export function missingFields(preferences: DentalPreferences): IntakeField[] {
  return (["budget", "ride"] as const).filter(field => preferences[field] === undefined);
}

const key = "lifeline:dental-intake:v1";
export type IntakeDraft = { known: DentalPreferences; answers: DentalPreferences; index: number };
export function readDraft(): IntakeDraft | null {
  try {
    const draft = JSON.parse(sessionStorage.getItem(key) ?? "null");
    if (!draft || !draft.known || !draft.answers || !Number.isInteger(draft.index)) return null;
    return missingFields(draft.known)[draft.index] ? draft : null;
  } catch { return null; }
}
export function saveDraft(draft: IntakeDraft | null) {
  try {
    if (draft) sessionStorage.setItem(key, JSON.stringify(draft));
    else sessionStorage.removeItem(key);
  } catch { /* The current page can still complete the demo. */ }
}
