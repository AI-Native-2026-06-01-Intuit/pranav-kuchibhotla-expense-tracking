import { useEffect, useRef } from 'react';
import { useChat } from '@ai-sdk/react';
import { useParams } from 'react-router-dom';

const DEFAULT_MERCHANT_ID = 'stub-id-1';

const MerchantChatPanel = () => {
  const { id: paramId } = useParams<{ id: string }>();
  const id = paramId ?? DEFAULT_MERCHANT_ID;

  const {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    status,
    stop,
    reload,
    error,
  } = useChat({
    id: `merchant-${id}`,
    api: '/api/chat',
  });

  const isLoading = status === 'submitted' || status === 'streaming';
  const canSend = input.trim() !== '' && !isLoading;

  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <section aria-label="merchant-chat">
      <h1>Chat about merchant {id}</h1>
      <ul aria-label="chat-transcript">
        {messages.map((message) => (
          <li key={message.id} data-role={message.role}>
            <strong>{message.role}:</strong> {message.content}
          </li>
        ))}
      </ul>
      <div ref={endRef} />
      {isLoading && <div role="status">Assistant is replying…</div>}
      {error && <div role="alert">Error: {error.message}</div>}
      <form aria-label="chat-input" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={handleInputChange}
          placeholder="Ask about this merchant…"
          aria-label="chat-message"
        />
        <button type="submit" disabled={!canSend}>
          {isLoading ? 'Sending…' : 'Send'}
        </button>
        <button type="button" onClick={stop} disabled={!isLoading}>
          Stop
        </button>
        <button
          type="button"
          onClick={() => {
            void reload();
          }}
          disabled={isLoading}
        >
          Regenerate
        </button>
      </form>
    </section>
  );
};

export default MerchantChatPanel;
