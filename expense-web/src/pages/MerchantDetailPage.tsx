import { useState } from 'react';
import { useMerchant } from '../hooks/useMerchant';
import ThresholdSlider from '../components/ThresholdSlider';
import ThresholdReadout from '../components/ThresholdReadout';

const MerchantDetailPage = () => {
  const [threshold, setThreshold] = useState<number>(50);
  const { data, loading, error } = useMerchant('stub-id-1');

  if (loading) {
    return <p>Loading merchant…</p>;
  }
  if (error !== null) {
    return <p role="alert">Error: {error}</p>;
  }
  if (data === null) {
    return <p>No merchant found.</p>;
  }

  return (
    <section>
      <h1>Merchant {data.id}</h1>
      <dl>
        <dt>MCC code</dt>
        <dd>{data.mccCode}</dd>
        <dt>Transaction count</dt>
        <dd>{data.transactionCount}</dd>
        <dt>Total spend</dt>
        <dd>{data.totalSpend}</dd>
      </dl>
      <h2>Lines</h2>
      <ul>
        {data.lines.map((line) => (
          <li key={line.id}>
            <span>{line.id}</span>: <span>{line.amount}</span>
          </li>
        ))}
      </ul>
      <ThresholdSlider value={threshold} onChange={setThreshold} />
      <ThresholdReadout value={threshold} />
    </section>
  );
};

export default MerchantDetailPage;
