import { Hono } from 'hono';
import { streamText, type CoreMessage } from 'ai';
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import { z } from 'zod';

// Threat model / buffering:
// This proxy holds the upstream provider details (baseURL, model id, and any
// future API key). The browser only calls /api/chat and never learns where
// the upstream actually lives. We must NOT buffer the response: SSE has to
// stream chunk by chunk so the UI can render tokens as they arrive, so the
// SSE headers below explicitly disable proxy/CDN buffering.

const provider = createOpenAICompatible({
  name: 'uptime-crew',
  baseURL: 'http://localhost:8080/ai',
});

const SYSTEM_PROMPT =
  'You are an assistant that helps engineers categorise merchant expenses. ' +
  'When asked about a merchant, answer clearly and concisely.';

const MessageSchema = z.object({
  role: z.enum(['system', 'user', 'assistant']),
  content: z.string(),
});

const BodySchema = z.object({
  messages: z.array(MessageSchema),
});

const SSE_HEADERS = {
  'Content-Type': 'text/event-stream',
  'Cache-Control': 'no-cache, no-transform',
  Connection: 'keep-alive',
  'X-Accel-Buffering': 'no',
} as const;

export const chatRoute = new Hono();

chatRoute.post('/', async (c) => {
  let raw: unknown;
  try {
    raw = await c.req.json();
  } catch {
    return c.json({ error: 'invalid JSON body' }, 400);
  }

  const parsed = BodySchema.safeParse(raw);
  if (!parsed.success) {
    return c.json({ error: 'invalid request body' }, 400);
  }

  const messages: CoreMessage[] = parsed.data.messages.map((m) => ({
    role: m.role,
    content: m.content,
  }));

  try {
    const result = streamText({
      model: provider.chatModel('uptime-crew-assistant'),
      system: SYSTEM_PROMPT,
      messages,
      abortSignal: c.req.raw.signal,
    });

    // Successful path: hand the data stream straight to the client. Per-chunk
    // upstream failures arrive as error frames inside the data stream itself,
    // which the AI SDK client surfaces via `error` on useChat.
    return result.toDataStreamResponse({ headers: { ...SSE_HEADERS } });
  } catch (err) {
    // Only triggers if streamText setup throws synchronously. A client abort
    // shows up as an AbortError — don't dress that up as a 502.
    if (err instanceof Error && err.name === 'AbortError') {
      return new Response(null, { status: 499 });
    }
    const detail = err instanceof Error ? err.message : 'unknown error';
    return c.json({ error: 'upstream chat failed', detail }, 502);
  }
});
