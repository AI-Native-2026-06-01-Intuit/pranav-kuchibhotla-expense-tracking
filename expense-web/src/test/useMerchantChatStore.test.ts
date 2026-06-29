import { describe, it, expect, beforeEach } from 'vitest';
import type { Message } from '@ai-sdk/react';
import { useMerchantChatStore } from '../stores/useMerchantChatStore';

const assistantMessage = (id: string, content: string): Message => ({
  id,
  role: 'assistant',
  content,
});

describe('useMerchantChatStore', () => {
  beforeEach(() => {
    window.localStorage.clear();
    useMerchantChatStore.setState(
      useMerchantChatStore.getInitialState(),
      true,
    );
  });

  it('appendAssistantMessage appends exactly one completed assistant message', () => {
    useMerchantChatStore
      .getState()
      .appendAssistantMessage(assistantMessage('m-1', 'first'));
    expect(useMerchantChatStore.getState().messages).toHaveLength(1);
    expect(useMerchantChatStore.getState().messages[0]?.content).toBe('first');
  });

  it('preserves order across multiple appends', () => {
    const { appendAssistantMessage } = useMerchantChatStore.getState();
    appendAssistantMessage(assistantMessage('m-1', 'first'));
    appendAssistantMessage(assistantMessage('m-2', 'second'));
    expect(
      useMerchantChatStore.getState().messages.map((m) => m.content),
    ).toEqual(['first', 'second']);
  });

  it('clear empties messages', () => {
    useMerchantChatStore
      .getState()
      .appendAssistantMessage(assistantMessage('m-1', 'first'));
    useMerchantChatStore.getState().clear();
    expect(useMerchantChatStore.getState().messages).toEqual([]);
  });

  it('writes serialized state to localStorage under uc:merchant-chat', () => {
    useMerchantChatStore
      .getState()
      .appendAssistantMessage(assistantMessage('m-1', 'persisted'));

    const raw = window.localStorage.getItem('uc:merchant-chat');
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw ?? '{}') as {
      state?: { messages?: Array<{ content?: string }> };
    };
    expect(parsed.state?.messages?.[0]?.content).toBe('persisted');
  });
});
