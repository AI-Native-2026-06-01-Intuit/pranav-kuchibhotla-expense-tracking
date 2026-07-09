import { useQuery } from '@apollo/client';
import { LatestMerchantsDocument } from '../gql/generated/graphql';

const MerchantListPage = () => {
  const { loading, error, data } = useQuery(LatestMerchantsDocument);

  if (loading) {
    return <div role="status">Loading merchants…</div>;
  }
  if (error) {
    return <div role="alert">{error.message}</div>;
  }

  const merchants = data?.latestMerchants ?? [];
  if (merchants.length === 0) {
    return <p>No merchants yet.</p>;
  }

  return (
    <ul aria-label="merchant-list">
      {merchants.map((m) => (
        <li key={m.id}>
          <a href={`/merchants/${m.id}`}>{m.name}</a>
        </li>
      ))}
    </ul>
  );
};

export default MerchantListPage;
