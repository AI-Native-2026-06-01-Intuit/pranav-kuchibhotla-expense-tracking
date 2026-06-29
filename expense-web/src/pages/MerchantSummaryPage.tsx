import { useMutation } from '@apollo/client';
import { useParams } from 'react-router-dom';
import { SummarizeMerchantDocument } from '../gql/generated/graphql';

const DEFAULT_MERCHANT_ID = 'stub-id-1';

const MerchantSummaryPage = () => {
  const { id: paramId } = useParams<{ id: string }>();
  const id = paramId ?? DEFAULT_MERCHANT_ID;
  const [summarize, { data, loading, error }] = useMutation(SummarizeMerchantDocument);

  const onClick = () => {
    void summarize({
      variables: { id },
      optimisticResponse: {
        summarizeMerchant: {
          __typename: 'MerchantSummary',
          id,
          summaryText: '...thinking...',
          confidence: 'MEDIUM',
        },
      },
    });
  };

  const summary = data?.summarizeMerchant;
  const optimisticPlaceholder = loading && !summary;

  return (
    <section aria-label="merchant-summary">
      <h1>Summarize merchant {id}</h1>
      <button onClick={onClick} disabled={loading}>Summarize</button>
      {error && <div role="alert">{error.message}</div>}
      {optimisticPlaceholder && (
        <article aria-label="summary-card">
          <p>...thinking...</p>
          <small>confidence: MEDIUM</small>
        </article>
      )}
      {summary && (
        <article aria-label="summary-card">
          <p>{summary.summaryText}</p>
          <small>confidence: {summary.confidence}</small>
        </article>
      )}
    </section>
  );
};

export default MerchantSummaryPage;
