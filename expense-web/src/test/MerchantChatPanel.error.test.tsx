import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import MerchantChatPanel from '../pages/MerchantChatPanel';
import { useMerchantChatStore } from '../stores/useMerchantChatStore';
import { server } from './server';
import { makeChatHandler, resetChatCallCount } from './sse-handlers';

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/merchants/:id/chat" element={<MerchantChatPanel />} />
      </Routes>
    </MemoryRouter>,
  );

describe('MerchantChatPanel error handling', () => {
  beforeEach(() => {
    window.localStorage.clear();
    useMerchantChatStore.setState(
      useMerchantChatStore.getInitialState(),
      true,
    );
    resetChatCallCount();
  });

  it('surfaces role="alert" when /api/chat returns HTTP 500', async () => {
    server.use(
      http.post('/api/chat', () =>
        HttpResponse.json({ error: 'upstream boom' }, { status: 500 }),
      ),
    );

    const user = userEvent.setup();
    renderAt('/merchants/stub-id-1/chat');

    await user.type(screen.getByLabelText('chat-message'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(
      await screen.findByRole('alert', undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it('surfaces role="alert" when the SSE stream body is malformed', async () => {
    server.use(
      http.post(
        '/api/chat',
        () =>
          new HttpResponse('this is not a valid data-stream frame', {
            headers: {
              'Content-Type': 'text/event-stream',
              'X-Vercel-AI-Data-Stream': 'v1',
            },
          }),
      ),
    );

    const user = userEvent.setup();
    renderAt('/merchants/stub-id-1/chat');

    await user.type(screen.getByLabelText('chat-message'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(
      await screen.findByRole('alert', undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it('clears the alert once a follow-up send succeeds', async () => {
    server.use(
      http.post(
        '/api/chat',
        () => HttpResponse.json({ error: 'boom' }, { status: 500 }),
        { once: true },
      ),
      makeChatHandler(),
    );

    const user = userEvent.setup();
    renderAt('/merchants/stub-id-1/chat');

    await user.type(screen.getByLabelText('chat-message'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByRole('alert', undefined, { timeout: 3000 });

    await user.type(screen.getByLabelText('chat-message'), 'again');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(
      () => {
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });
});
