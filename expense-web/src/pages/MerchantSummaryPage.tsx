import { useMutation } from '@apollo/client';
import { SummarizeMerchantDocument } from '../gql/generated/graphql';

// react-router-dom is not installed yet (lands in Task 3). Use a stable
// fallback id so the page is reachable manually for now.
const DEFAULT_MERCHANT_ID = 'stub-id-1';

const MerchantSummaryPage = () => {
  const id = DEFAULT_MERCHANT_ID;
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

  return (
    <section aria-label="merchant-summary">
      <h1>Summarize merchant {id}</h1>
      <button onClick={onClick} disabled={loading}>Summarize</button>
      {error && <div role="alert">{error.message}</div>}
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
