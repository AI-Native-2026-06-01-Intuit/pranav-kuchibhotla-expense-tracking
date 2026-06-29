import { useChat } from '@ai-sdk/react';
import { useParams } from 'react-router-dom';

const DEFAULT_MERCHANT_ID = 'stub-id-1';

const MerchantChatPanel = () => {
  const { id: paramId } = useParams<{ id: string }>();
  const id = paramId ?? DEFAULT_MERCHANT_ID;

  const { messages, input, handleInputChange, handleSubmit, status } = useChat({
    id: `merchant-${id}`,
    api: '/api/chat',
  });

  const isLoading = status === 'submitted' || status === 'streaming';

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
      <form aria-label="chat-input" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={handleInputChange}
          placeholder="Ask about this merchant…"
          aria-label="chat-message"
        />
        <button type="submit" disabled={isLoading}>
          {isLoading ? 'Sending…' : 'Send'}
        </button>
      </form>
    </section>
  );
};

export default MerchantChatPanel;
