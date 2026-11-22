"use client";

import { useState } from "react";
import { missingFields, type IntakeDraft, type DentalPreferences } from "@/lib/demoIntake";
import SimplePanel from "./SimplePanel";

type Props = {
  draft: IntakeDraft;
  change: (draft: IntakeDraft | null) => void;
  finish: (preferences: DentalPreferences) => void;
  /** When true, eyebrow says dental demo; live guided intake leaves it off. */
  demo?: boolean;
};

export default function DemoIntakeQuestion({ draft, change, finish, demo = true }: Props) {
  const fields = missingFields(draft.known);
  const field = fields[draft.index];
  const budget = field === "budget";
  const saved = draft.answers[field];
  const [choice, setChoice] = useState(saved === undefined ? "" : saved === null ? "none" : String(saved));
  const [amount, setAmount] = useState(typeof saved === "number" ? String(saved) : "");
  const last = draft.index === fields.length - 1;
  const options = budget
    ? [["amount", "Set a maximum"], ["none", "No maximum"]]
    : [["true", "Yes, I’ll need a ride"], ["false", "No, I have a ride"]];
  const selected = budget && choice !== "" && choice !== "none" ? "amount" : choice;
  return <main className="simple-main"><SimplePanel stage="request" demo={demo}
    title={budget ? "How much would you like to spend?" : "Will you need a ride?"}>
    <p className="intake-progress">Before we call · Question {draft.index + 1} of {fields.length}</p>
    <p>{budget ? "We’ll look for a dental cleaning within your budget." : "This helps AIGranni plan transportation if you approve an appointment."}</p>
    <form className="simple-form" onSubmit={e => {
      e.preventDefault();
      if (!selected) return;
      const value = budget ? (selected === "none" ? null : Number(amount)) : selected === "true";
      const answers = { ...draft.answers, [field]: value };
      if (last) finish({ ...draft.known, ...answers });
      else change({ ...draft, answers, index: draft.index + 1 });
    }}>
      <fieldset className="intake-options"><legend className="sr-only">{budget ? "Budget preference" : "Ride preference"}</legend>
        {options.map(([value,label]) => <label key={value}><input type="radio" name={field} value={value} required
          checked={selected === value} onChange={() => setChoice(value)}/>{label}</label>)}
      </fieldset>
      {budget && selected === "amount" && <label>Maximum in dollars
        <input className="intake-amount" type="number" required min="0" max="100000" step="0.01" inputMode="decimal"
          value={amount} onChange={e => setAmount(e.target.value)}/></label>}
      <div className="form-actions">
        <button className="primary-action" disabled={!selected || (selected === "amount" && !amount)}>{last ? "Start clinic calls" : "Continue"}</button>
        <button type="button" className="quiet-button" onClick={() => change(draft.index ? { ...draft, index: draft.index - 1 } : null)}>
          {draft.index ? "Previous question" : "Start over"}</button>
      </div>
    </form>
  </SimplePanel></main>;
}
