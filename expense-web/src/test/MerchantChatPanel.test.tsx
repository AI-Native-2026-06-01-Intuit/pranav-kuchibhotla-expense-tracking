import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import MerchantChatPanel from '../pages/MerchantChatPanel';
import { useMerchantChatStore } from '../stores/useMerchantChatStore';
import { server } from './server';
import {
  chatCallCount,
  makeChatHandler,
  resetChatCallCount,
} from './sse-handlers';

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/merchants/:id/chat" element={<MerchantChatPanel />} />
      </Routes>
    </MemoryRouter>,
  );

const FULL_REPLY = 'stub merchant reply.';

describe('MerchantChatPanel', () => {
  beforeEach(() => {
    window.localStorage.clear();
    useMerchantChatStore.setState(
      useMerchantChatStore.getInitialState(),
      true,
    );
    resetChatCallCount();
  });

  it('renders the merchant id from the route param in the heading', () => {
    renderAt('/merchants/stub-id-1/chat');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'stub-id-1',
    );
  });

  it('disables Send while input is empty and enables it once text is typed', async () => {
    const user = userEvent.setup();
    renderAt('/merchants/stub-id-1/chat');

    const send = screen.getByRole('button', { name: 'Send' });
    expect(send).toBeDisabled();

    await user.type(screen.getByLabelText('chat-message'), 'hello');
    expect(send).toBeEnabled();
  });

  it('streams default response and shows assistant li with full text', async () => {
    const user = userEvent.setup();
    renderAt('/merchants/stream-test/chat');

    await user.type(screen.getByLabelText('chat-message'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    const matches = await screen.findAllByText(FULL_REPLY, undefined, {
      timeout: 3000,
    });
    const last = matches[matches.length - 1];
    expect(last?.closest('li')).toHaveAttribute('data-role', 'assistant');
  });

  it('shows status "Assistant is replying…" during stream and removes it on finish', async () => {
    server.use(makeChatHandler({ delayMs: 20 }));
    const user = userEvent.setup();
    renderAt('/merchants/stub-id-1/chat');

    await user.type(screen.getByLabelText('chat-message'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByRole('status')).toHaveTextContent(
      /assistant is replying/i,
    );

    await waitFor(
      () => {
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it('Stop button is disabled at rest and enabled while streaming', async () => {
    server.use(makeChatHandler({ delayMs: 20 }));
    const user = userEvent.setup();
    renderAt('/merchants/stub-id-1/chat');

    const stop = screen.getByRole('button', { name: 'Stop' });
    expect(stop).toBeDisabled();

    await user.type(screen.getByLabelText('chat-message'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => {
      expect(stop).toBeEnabled();
    });

    await waitFor(
      () => {
        expect(stop).toBeDisabled();
      },
      { timeout: 3000 },
    );
  });

  it('clicking Stop while streaming causes the status indicator to disappear', async () => {
    server.use(makeChatHandler({ delayMs: 50 }));
    const user = userEvent.setup();
    renderAt('/merchants/stub-id-1/chat');

    await user.type(screen.getByLabelText('chat-message'), 'hi');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    const stop = await screen.findByRole('button', { name: 'Stop' });
    await waitFor(() => {
      expect(stop).toBeEnabled();
    });
    await user.click(stop);

    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });
  });

  it('Regenerate sends a second POST to /api/chat', async () => {
    const user = userEvent.setup();
    // Unique merchant id so this test's useChat hook starts from a fresh
    // module-scoped chat store instead of inheriting earlier transcripts.
    renderAt('/merchants/regen-test/chat');

    await user.type(screen.getByLabelText('chat-message'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(
      () => {
        expect(chatCallCount.value).toBe(1);
      },
      { timeout: 3000 },
    );
    await screen.findAllByText(FULL_REPLY, undefined, { timeout: 3000 });

    await user.click(screen.getByRole('button', { name: 'Regenerate' }));

    await waitFor(
      () => {
        expect(chatCallCount.value).toBeGreaterThanOrEqual(2);
      },
      { timeout: 3000 },
    );
  });

  it('persists exactly one completed assistant message via onFinish', async () => {
    const user = userEvent.setup();
    renderAt('/merchants/persist-test/chat');

    await user.type(screen.getByLabelText('chat-message'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findAllByText(FULL_REPLY, undefined, { timeout: 3000 });

    await waitFor(() => {
      const persisted = useMerchantChatStore.getState().messages;
      expect(persisted).toHaveLength(1);
      expect(persisted[0]?.role).toBe('assistant');
      expect(persisted[0]?.content).toBe(FULL_REPLY);
    });
  });
});
