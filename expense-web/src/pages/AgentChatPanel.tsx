import { useEffect, useRef, useState } from 'react';
import type { JSONValue } from 'ai';
import { useChat } from '@ai-sdk/react';

// W7D5 agent panel. This is a *new* page that talks to the
// expense-agent-svc directly. It does NOT replace the merchant chat
// path (`/api/chat` via Hono proxy) — that still ships the tool-loop
// UX. This panel is the endpoint for the multi-agent supervisor graph.

const DEFAULT_AGENT_URL = 'http://localhost:8080';
const RAW_AGENT_URL: unknown = import.meta.env.VITE_EXPENSE_AGENT_URL;
const AGENT_URL = (
  typeof RAW_AGENT_URL === 'string' && RAW_AGENT_URL.length > 0
    ? RAW_AGENT_URL
    : DEFAULT_AGENT_URL
).replace(/\/$/, '');
const AGENT_ENDPOINT = `${AGENT_URL}/v1/chat/stream`;

const ALLOWED_TENANTS = ['tenant-a', 'tenant-b', 'tenant-c'] as const;
type Tenant = (typeof ALLOWED_TENANTS)[number];

interface AgentCitation {
  readonly doc_id: string;
  readonly quote: string;
}

interface AgentFinalAnswer {
  readonly text: string;
  readonly citations: readonly AgentCitation[];
  readonly confidence: number;
}

interface AgentStreamError {
  readonly error: string;
  readonly message: string;
}

const SAFE_ERROR_MESSAGES: Record<string, string> = {
  recursion_limit: 'The request exceeded the permitted graph steps.',
  budget_exceeded: 'The request exceeded its cost budget.',
  request_context_unavailable: 'The request could not be continued.',
  internal_error: 'The request could not be completed.',
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const asAgentFinalAnswer = (value: unknown): AgentFinalAnswer | null => {
  if (!isRecord(value)) {
    return null;
  }
  const text = value.text;
  const confidence = value.confidence;
  const citationsRaw = value.citations;
  if (typeof text !== 'string' || typeof confidence !== 'number') {
    return null;
  }
  const clampedConfidence = Math.max(0, Math.min(1, confidence));
  const citations: AgentCitation[] = [];
  if (Array.isArray(citationsRaw)) {
    for (const raw of citationsRaw) {
      if (isRecord(raw) && typeof raw.doc_id === 'string' && typeof raw.quote === 'string') {
        citations.push({ doc_id: raw.doc_id, quote: raw.quote });
      }
    }
  }
  return { text, citations, confidence: clampedConfidence };
};

const asAgentStreamError = (value: unknown): AgentStreamError | null => {
  if (!isRecord(value)) {
    return null;
  }
  const code = value.error;
  if (typeof code !== 'string') {
    return null;
  }
  return {
    error: code,
    message:
      SAFE_ERROR_MESSAGES[code] ??
      SAFE_ERROR_MESSAGES.internal_error ??
      'The request could not be completed.',
  };
};

const pickFinalAnswer = (
  data: readonly JSONValue[] | undefined,
): AgentFinalAnswer | null => {
  if (!data) {
    return null;
  }
  // AI SDK v4 packs channel-2 values into `data` in emission order.
  // The last valid FinalAnswer-shaped entry wins.
  for (let i = data.length - 1; i >= 0; i -= 1) {
    const parsed = asAgentFinalAnswer(data[i]);
    if (parsed !== null) {
      return parsed;
    }
  }
  return null;
};

const streamErrorFromUseChat = (
  error: Error | undefined,
): AgentStreamError | null => {
  // AI SDK v4 channel-3 throws through `useChat.error`; the thrown
  // Error's message is the raw code string we shipped from the
  // backend. Look it up in the safe catalogue so the raw slug is
  // never rendered to the user.
  if (!error) {
    return null;
  }
  return asAgentStreamError({ error: error.message });
};

const generateThreadId = (): string => {
  // Local ID stable for the conversation. If the server ever returns
  // an X-Thread-Id on the first response we prefer that (see
  // onResponse below).
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2);
  return `web-${random}`;
};

const AgentChatPanel = () => {
  const [tenantId, setTenantId] = useState<Tenant>('tenant-a');
  const threadIdRef = useRef<string>(generateThreadId());

  const {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    status,
    error,
    data,
    stop,
  } = useChat({
    api: AGENT_ENDPOINT,
    // Convert useChat's messages array into the backend's ChatRequest
    // shape. The backend never sees the full message history — the
    // W7D5 graph reconstructs conversation state from its own
    // PostgresSaver checkpoint keyed by thread_id.
    experimental_prepareRequestBody: ({ messages: msgs }) => {
      const last = msgs[msgs.length - 1];
      const question = typeof last?.content === 'string' ? last.content : '';
      return {
        question,
        tenant_id: tenantId,
        thread_id: threadIdRef.current,
      };
    },
    onResponse: (response) => {
      // Prefer the server-supplied thread_id on the first response so
      // a resumed checkpoint stays consistent even if the browser
      // reload lost our local reference. The header is case-insensitive.
      const returned = response.headers.get('X-Thread-Id');
      if (returned && returned.length > 0) {
        threadIdRef.current = returned;
      }
    },
  });

  const isLoading = status === 'submitted' || status === 'streaming';
  const canSend = input.trim() !== '' && !isLoading;

  const finalAnswer = pickFinalAnswer(data);
  const streamError = streamErrorFromUseChat(error);

  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <section aria-label="agent-chat">
      <h1>Agent chat</h1>
      <label>
        Tenant:{' '}
        <select
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value as Tenant)}
          aria-label="tenant-select"
        >
          {ALLOWED_TENANTS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      <div role="log" aria-label="chat-transcript" aria-live="polite">
        <ul>
          {messages.map((message) => (
            <li key={message.id} data-role={message.role}>
              <strong>{message.role}:</strong> {message.content}
            </li>
          ))}
        </ul>
      </div>
      <div ref={endRef} />
      {isLoading && <div role="status">Assistant is replying…</div>}
      {streamError && (
        <div role="alert" data-testid="agent-stream-error">
          {streamError.message}
        </div>
      )}
      {finalAnswer && (
        <aside aria-label="final-answer" data-testid="agent-final-answer">
          <p>Confidence: {finalAnswer.confidence.toFixed(2)}</p>
          {finalAnswer.citations.length > 0 && (
            <ol aria-label="citations">
              {finalAnswer.citations.map((c, i) => (
                <li key={`${c.doc_id}-${i}`}>
                  <cite>{c.doc_id}</cite>: {c.quote}
                </li>
              ))}
            </ol>
          )}
        </aside>
      )}
      <form aria-label="chat-input" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={handleInputChange}
          placeholder="Ask the agent…"
          aria-label="chat-message"
        />
        <button type="submit" disabled={!canSend}>
          {isLoading ? 'Sending…' : 'Send'}
        </button>
        <button type="button" onClick={stop} disabled={!isLoading}>
          Stop
        </button>
      </form>
    </section>
  );
};

export default AgentChatPanel;
// eslint-disable-next-line react-refresh/only-export-components
export { AGENT_ENDPOINT, ALLOWED_TENANTS };
