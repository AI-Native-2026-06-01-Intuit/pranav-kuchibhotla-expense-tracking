// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import AgentChatPanel, { AGENT_ENDPOINT } from '../pages/AgentChatPanel';
import { server } from './server';

// W7D5 backend contract (see expense-agent-svc/src/expense_agent_svc/sse.py):
//   0:<json string>       -> text delta on channel 0
//   2:<json object>       -> typed FinalAnswer on channel 2
//   3:<json object>       -> safe error frame on channel 3
// The AI SDK v4 useChat data-stream transport surfaces channel-2/3 frames
// on the `data` array. This suite drives the panel through MSW-scripted
// backend responses and asserts only what the UI does with them.

interface RecordedCall {
  readonly url: string;
  readonly body: {
    question?: string;
    tenant_id?: string;
    thread_id?: string;
    [k: string]: unknown;
  };
  readonly returnedThreadId: string;
}

const encoder = new TextEncoder();

const streamFrames = (frames: readonly string[]): ReadableStream<Uint8Array> => {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame));
      }
      controller.close();
    },
  });
};

const RESPONSE_HEADERS = {
  'Content-Type': 'text/plain; charset=utf-8',
  'X-Vercel-AI-Data-Stream': 'v1',
  'Cache-Control': 'no-cache',
};

const installAgentHandler = (
  frames: readonly string[],
  serverThreadId: string,
  recorder: RecordedCall[],
) => {
  server.use(
    http.post(AGENT_ENDPOINT, async ({ request }) => {
      const raw = (await request.json()) as RecordedCall['body'];
      recorder.push({
        url: request.url,
        body: raw,
        returnedThreadId: serverThreadId,
      });
      return new HttpResponse(streamFrames(frames), {
        headers: {
          ...RESPONSE_HEADERS,
          'X-Thread-Id': serverThreadId,
        },
      });
    }),
  );
};

const renderPanel = () =>
  render(
    <MemoryRouter initialEntries={['/agent']}>
      <Routes>
        <Route path="/agent" element={<AgentChatPanel />} />
      </Routes>
    </MemoryRouter>,
  );

// AI SDK v4 wire grammar:
//   0:<json string>  -> text delta
//   2:<json array>   -> data values (we ship one FinalAnswer)
//   3:<json string>  -> error code slug (human message from the local catalogue)
const TEXT_ONE_FRAME = '0:"Hello "\n0:"world"\n';
const FINAL_ANSWER_FRAME = `2:${JSON.stringify([
  {
    text: 'Hello world',
    citations: [{ doc_id: 'd1', quote: 'a valid quote body' }],
    confidence: 0.82,
  },
])}\n`;
const ERROR_FRAME = `3:${JSON.stringify('budget_exceeded')}\n`;
const MALFORMED_FINAL_FRAME = `2:${JSON.stringify([{ confidence: 'not-a-number' }])}\n`;

describe('AgentChatPanel', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('renders the tenant selector and the compose form', () => {
    renderPanel();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Agent chat');
    expect(screen.getByLabelText('tenant-select')).toBeInTheDocument();
    expect(screen.getByLabelText('chat-message')).toBeInTheDocument();
  });

  it('sends question, tenant_id, and thread_id to VITE_EXPENSE_AGENT_URL', async () => {
    const recorder: RecordedCall[] = [];
    installAgentHandler([TEXT_ONE_FRAME, FINAL_ANSWER_FRAME], 'server-thread-1', recorder);

    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText('chat-message'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => {
      expect(recorder.length).toBeGreaterThanOrEqual(1);
    });

    const call = recorder[0]!;
    expect(call.url).toBe(AGENT_ENDPOINT);
    expect(call.body.question).toBe('hello');
    expect(call.body.tenant_id).toBe('tenant-a');
    expect(typeof call.body.thread_id).toBe('string');
    expect(call.body.thread_id).not.toBe('');
    // No internal fields — the backend generates request_id on its own.
    expect(call.body).not.toHaveProperty('request_id');
    expect(call.body).not.toHaveProperty('api_key');
    expect(call.body).not.toHaveProperty('authorization');
  });

  it('renders channel-0 text exactly once', async () => {
    const recorder: RecordedCall[] = [];
    installAgentHandler([TEXT_ONE_FRAME, FINAL_ANSWER_FRAME], 'server-thread-2', recorder);

    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText('chat-message'), 'hi');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => {
      const matches = screen.getAllByText(/Hello world/i);
      expect(matches.length).toBe(1);
    });
  });

  it('captures channel-2 FinalAnswer citations and confidence', async () => {
    const recorder: RecordedCall[] = [];
    installAgentHandler([FINAL_ANSWER_FRAME], 'server-thread-3', recorder);

    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText('chat-message'), 'policy?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    const finalAnswer = await screen.findByTestId('agent-final-answer');
    expect(finalAnswer).toHaveTextContent('Confidence: 0.82');
    const citations = await screen.findByRole('list', { name: 'citations' });
    expect(citations).toHaveTextContent('d1');
    expect(citations).toHaveTextContent('a valid quote body');
  });

  it('renders a safe channel-3 error message', async () => {
    const recorder: RecordedCall[] = [];
    installAgentHandler([ERROR_FRAME], 'server-thread-4', recorder);

    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText('chat-message'), 'over budget');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    const alert = await screen.findByTestId('agent-stream-error');
    expect(alert).toHaveTextContent('The request exceeded its cost budget.');
    // The raw backend error code is not user-facing.
    expect(alert.textContent).not.toContain('budget_exceeded');
  });

  it('does not crash on a malformed channel-2 payload', async () => {
    const recorder: RecordedCall[] = [];
    installAgentHandler([MALFORMED_FINAL_FRAME], 'server-thread-5', recorder);

    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText('chat-message'), 'break the parser');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    // Wait long enough for the response to be consumed; nothing to
    // assert-crash means the render survived.
    await waitFor(() => {
      expect(recorder.length).toBeGreaterThanOrEqual(1);
    });
    // No FinalAnswer aside is rendered because normalisation rejected
    // the payload (missing text, non-numeric confidence).
    expect(screen.queryByTestId('agent-final-answer')).toBeNull();
  });

  it('retains the server X-Thread-Id on the second turn', async () => {
    const recorder: RecordedCall[] = [];
    installAgentHandler([TEXT_ONE_FRAME, FINAL_ANSWER_FRAME], 'server-thread-A', recorder);

    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText('chat-message'), 'first');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(recorder.length).toBe(1));

    // Second turn — installAgentHandler again returns a new server id
    // but the panel should re-send the FIRST server id (proving retention).
    installAgentHandler([TEXT_ONE_FRAME, FINAL_ANSWER_FRAME], 'server-thread-B', recorder);
    await user.type(screen.getByLabelText('chat-message'), 'second');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(recorder.length).toBe(2));

    expect(recorder[1]!.body.thread_id).toBe('server-thread-A');
  });

  it('changes tenant_id when the user picks a different tenant', async () => {
    const recorder: RecordedCall[] = [];
    installAgentHandler([FINAL_ANSWER_FRAME], 'server-thread-t', recorder);

    const user = userEvent.setup();
    renderPanel();
    await user.selectOptions(screen.getByLabelText('tenant-select'), 'tenant-b');
    await user.type(screen.getByLabelText('chat-message'), 'hi');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(recorder.length).toBe(1));
    expect(recorder[0]!.body.tenant_id).toBe('tenant-b');
  });
});
