import { http, HttpResponse } from 'msw';

// Vercel AI SDK "data" stream protocol: each frame is `<code>:<json>\n`.
// We only need text frames (`0:"..."`) and a finish frame (`d:{...}`).
// The header `X-Vercel-AI-Data-Stream: v1` is what the SDK sniffs to pick
// the data-protocol parser; without it the client falls back to plain text.

const encoder = new TextEncoder();

const DEFAULT_CHUNKS: ReadonlyArray<string> = ['stub ', 'merchant ', 'reply.'];

const FINISH_FRAME =
  `d:${JSON.stringify({
    finishReason: 'stop',
    usage: { promptTokens: 1, completionTokens: 3 },
  })}\n`;

interface StreamOptions {
  readonly chunks?: ReadonlyArray<string>;
  readonly delayMs?: number;
}

export const makeChatStream = ({
  chunks = DEFAULT_CHUNKS,
  delayMs = 0,
}: StreamOptions = {}): ReadableStream<Uint8Array> => {
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const chunk of chunks) {
        if (delayMs > 0) {
          await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
        }
        controller.enqueue(encoder.encode(`0:${JSON.stringify(chunk)}\n`));
      }
      if (delayMs > 0) {
        await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
      }
      controller.enqueue(encoder.encode(FINISH_FRAME));
      controller.close();
    },
  });
};

const SSE_HEADERS: HeadersInit = {
  'Content-Type': 'text/event-stream',
  'Cache-Control': 'no-cache, no-transform',
  'X-Vercel-AI-Data-Stream': 'v1',
};

// Tests can read/reset this to assert POST count (e.g. for Regenerate).
export const chatCallCount = { value: 0 };

export const resetChatCallCount = (): void => {
  chatCallCount.value = 0;
};

export const makeChatHandler = (options: StreamOptions = {}) =>
  http.post('/api/chat', () => {
    chatCallCount.value += 1;
    return new HttpResponse(makeChatStream(options), { headers: SSE_HEADERS });
  });

export const sseHandlers = [makeChatHandler()];
