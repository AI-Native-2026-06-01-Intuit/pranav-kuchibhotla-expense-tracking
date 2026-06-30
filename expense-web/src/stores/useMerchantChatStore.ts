import { create } from 'zustand';
import { devtools, persist, createJSONStorage } from 'zustand/middleware';
import type { Message } from '@ai-sdk/react';

interface ChatState {
  readonly messages: ReadonlyArray<Message>;
}

interface ChatActions {
  readonly appendAssistantMessage: (message: Message) => void;
  readonly clear: () => void;
}

type Store = ChatState & ChatActions;

const initialState: ChatState = {
  messages: [],
};

export const useMerchantChatStore = create<Store>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        // Called exactly once per completed assistant message, from useChat's
        // onFinish callback. Never call this on every token or every messages
        // change — that's what useChat already does in-memory.
        appendAssistantMessage: (message) =>
          set(
            (state) => ({ messages: [...state.messages, message] }),
            false,
            'chat/appendAssistantMessage',
          ),
        clear: () => set({ messages: [] }, false, 'chat/clear'),
      }),
      {
        name: 'uc:merchant-chat',
        storage: createJSONStorage(() => {
          // jsdom under Node 22+ omits localStorage; throwing here makes
          // zustand fall back to no-op storage so tests/SSR don't crash.
          if (
            typeof window === 'undefined' ||
            window.localStorage === undefined
          ) {
            throw new Error('localStorage unavailable');
          }
          return window.localStorage;
        }),
        partialize: (state) => ({ messages: state.messages }),
      },
    ),
    { name: 'useMerchantChatStore' },
  ),
);
