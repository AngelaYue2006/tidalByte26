"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { IconLock, IconMicrophone, IconMicrophoneOff, IconSend } from "@tabler/icons-react";
import { postRequest } from "@/lib/api";
import { VIEWERS, type Viewer } from "@/lib/viewer";

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((ev: { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null;
  onerror: ((ev: { error: string }) => void) | null;
  onend: (() => void) | null;
};

type SpeechWindow = Window & {
  SpeechRecognition?: new () => SpeechRecognitionLike;
  webkitSpeechRecognition?: new () => SpeechRecognitionLike;
};

export type RequestBarProps = {
  viewer: Viewer;
  simple?: boolean;
  demo?: boolean;
  onSent?: (text: string) => void;
  /** Chips from the live `request` event. */
  chips?: string[];
  /** Redacted/owner request text from the live event (owner may see it). */
  requestText?: string;
};

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function getSpeechRecognition(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const w = window as SpeechWindow;
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

/** Big mic + text input. Posts to /api/requests. Chips with `!` render green + lock. */
export default function RequestBar({ viewer, chips = [], requestText, simple, demo, onSent }: RequestBarProps) {
  const owner = VIEWERS.owner;
  const contact = VIEWERS.contact;
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [speechSupported, setSpeechSupported] = useState(true);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    setSpeechSupported(!!getSpeechRecognition());
    return () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    };
  }, []);

  async function submit(utterance: string) {
    const trimmed = utterance.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      if (!demo) await postRequest(viewer.viewerId, {
        owner_id: owner.viewerId,
        actor_id: viewer.viewerId,
        text: trimmed,
        idempotency_key: newIdempotencyKey(),
      });
      setText("");
      onSent?.(trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send request");
    } finally {
      setSubmitting(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(text);
  }

  function toggleMic() {
    setError(null);
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    const recognition = getSpeechRecognition();
    if (!recognition) {
      setSpeechSupported(false);
      setError("Speech recognition is not available in this browser.");
      return;
    }
    recognitionRef.current = recognition;
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.onresult = (ev) => {
      const parts: string[] = [];
      for (let i = 0; i < ev.results.length; i++) {
        parts.push(ev.results[i][0].transcript);
      }
      const spoken = parts.join(" ").trim();
      setText(spoken);
      const last = ev.results[ev.results.length - 1];
      if (last?.isFinal) void submit(spoken);
    };
    recognition.onerror = (ev) => {
      setListening(false);
      if (ev.error !== "aborted" && ev.error !== "no-speech") {
        setError(`Microphone error: ${ev.error}`);
      }
    };
    recognition.onend = () => setListening(false);
    try {
      recognition.start();
      setListening(true);
    } catch {
      setError("Could not start the microphone.");
      setListening(false);
    }
  }

  if (simple) return (
    <form className="simple-form" onSubmit={onSubmit}>
      <label htmlFor="simple-request">{viewer.role === "contact" ? "Tell GranniAI what Mary needs" : "Tell GranniAI what you need"}</label>
      <textarea id="simple-request" rows={3} value={text} disabled={submitting}
        placeholder={viewer.role === "contact" ? "For example, Mary needs a dental cleaning this week." : "For example, I need a dental cleaning this week."} onChange={e => setText(e.target.value)} />
      <div className="form-actions">
        <button className="primary-action" disabled={!text.trim() || submitting} type="submit">
          <IconSend size={20}/>{submitting ? "Sending…" : "Send request"}
        </button>
        {speechSupported && <button className="quiet-button" type="button" onClick={toggleMic} disabled={submitting}
          aria-pressed={listening}><IconMicrophone size={20}/>{listening ? "Stop listening" : "Speak request"}</button>}
      </div>
      {error && <p role="alert">{error}</p>}
    </form>
  );

  const forLine =
    viewer.role === "contact"
      ? `Submitting for ${owner.name}`
      : `Request for ${owner.name}`;

  const displayText =
    requestText?.trim() ||
    (text.trim() ? text : "Waiting for a request…");
  const showTypedAsPending = !requestText && !!text.trim();

  return (
    <section className="card request-bar" aria-label="Request">
      <div className="request-bar-row">
        <button
          type="button"
          className={`mic-btn${listening ? " mic-btn-live" : ""}`}
          onClick={toggleMic}
          disabled={submitting || !speechSupported}
          aria-pressed={listening}
          aria-label={listening ? "Stop listening" : "Speak a request"}
          title={speechSupported ? "Speak a request" : "Speech not supported"}
        >
          {listening ? <IconMicrophoneOff size={28} stroke={1.75} /> : <IconMicrophone size={28} stroke={1.75} />}
        </button>

        <div className="request-bar-main">
          <div className="faint request-bar-people">
            {owner.name} · emergency contact: {contact.name}
          </div>
          <div className="faint request-bar-for">{forLine}</div>
          <p
            className={
              requestText || showTypedAsPending ? "request-bar-text" : "request-bar-text muted"
            }
          >
            {listening ? "Listening…" : displayText}
          </p>

          {chips.length > 0 ? (
            <div className="chips" aria-label="Request chips">
              {chips.map((chip) => {
                const onDevice = chip.startsWith("!");
                const label = onDevice ? chip.slice(1) : chip;
                return (
                  <span key={chip} className={`chip${onDevice ? " chip-good" : ""}`}>
                    {onDevice ? <IconLock size={14} stroke={1.75} aria-hidden /> : null}
                    {label}
                  </span>
                );
              })}
            </div>
          ) : null}

          <form className="request-bar-form" onSubmit={onSubmit}>
            <label className="sr-only" htmlFor="request-text">
              Request text
            </label>
            <input
              id="request-text"
              className="request-input"
              type="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Type a request, or use the microphone"
              disabled={submitting}
              autoComplete="off"
            />
            <button
              type="submit"
              className="request-send"
              disabled={submitting || !text.trim()}
              aria-label="Send request"
            >
              <IconSend size={18} stroke={1.75} />
              Send
            </button>
          </form>

          {error ? <p className="request-bar-error">{error}</p> : null}
        </div>
      </div>
    </section>
  );
}
