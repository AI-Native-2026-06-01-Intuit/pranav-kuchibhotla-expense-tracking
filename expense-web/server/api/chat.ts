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

export const chatRoute = new Hono();

chatRoute.post('/', async (c) => {
  const raw: unknown = await c.req.json();
  const parsed = BodySchema.safeParse(raw);
  if (!parsed.success) {
    return c.json({ error: 'invalid request body' }, 400);
  }

  const messages: CoreMessage[] = parsed.data.messages.map((m) => ({
    role: m.role,
    content: m.content,
  }));

  const result = streamText({
    model: provider.chatModel('uptime-crew-assistant'),
    system: SYSTEM_PROMPT,
    messages,
    abortSignal: c.req.raw.signal,
  });

  return result.toDataStreamResponse({
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
});
