import { useEffect, useReducer, useState } from 'react';
import ThresholdSlider from '../components/ThresholdSlider';
import ThresholdReadout from '../components/ThresholdReadout';
import FilterStrip from '../components/FilterStrip';
import { useDebouncedSearch } from '../hooks/useDebouncedSearch';
import {
  INITIAL_DETAIL_STATE,
  detailReducer,
} from './MerchantDetailPage.reducer';
import type { Merchant, MerchantLine } from '../types/merchant';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const isMerchantLine = (value: unknown): value is MerchantLine =>
  isRecord(value) &&
  typeof value.id === 'string' &&
  typeof value.amount === 'string';

const isMerchant = (value: unknown): value is Merchant =>
  isRecord(value) &&
  typeof value.id === 'string' &&
  typeof value.mccCode === 'string' &&
  typeof value.transactionCount === 'number' &&
  typeof value.totalSpend === 'string' &&
  Array.isArray(value.lines) &&
  value.lines.every(isMerchantLine);

const MerchantDetailPage = () => {
  const [state, dispatch] = useReducer(detailReducer, INITIAL_DETAIL_STATE);
  const debouncedSearch = useDebouncedSearch();
  const [shouldThrow, setShouldThrow] = useState<boolean>(false);

  if (shouldThrow) {
    throw new Error('Dev-only merchant detail error');
  }

  useEffect(() => {
    let cancelled = false;
    dispatch({ type: 'fetch/start' });

    const load = async (): Promise<void> => {
      try {
        const response = await fetch('/mocks/merchant.json');
        if (!response.ok) {
          throw new Error(`Failed to load merchant: ${String(response.status)}`);
        }
        const raw: unknown = await response.json();
        if (cancelled) return;
        if (raw === null) {
          dispatch({ type: 'fetch/success', payload: null });
          return;
        }
        if (!isMerchant(raw)) {
          throw new Error('Merchant payload failed validation');
        }
        dispatch({ type: 'fetch/success', payload: raw });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : 'Unknown error';
        dispatch({ type: 'fetch/error', error: message });
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === 'idle' || state.status === 'loading') {
    return <p>Loading merchant…</p>;
  }
  if (state.status === 'error') {
    return <p role="alert">Error: {state.error}</p>;
  }
  if (state.status === 'empty') {
    return <p>Not found.</p>;
  }

  const { data } = state;
  return (
    <section>
      <FilterStrip />
      <p>Filtering for: &quot;{debouncedSearch}&quot;</p>
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
      <ThresholdSlider />
      <ThresholdReadout />
      {import.meta.env.DEV && (
        <button onClick={() => { setShouldThrow(true); }}>
          Trigger error
        </button>
      )}
    </section>
  );
};

export default MerchantDetailPage;
