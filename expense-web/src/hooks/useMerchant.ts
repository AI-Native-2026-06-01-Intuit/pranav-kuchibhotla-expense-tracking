import { useEffect, useState } from 'react';
import type { Merchant, MerchantLine } from '../types/merchant';

type MerchantState =
  | { readonly status: 'loading' }
  | { readonly status: 'ok'; readonly data: Merchant }
  | { readonly status: 'error'; readonly error: string };

interface UseMerchantResult {
  readonly data: Merchant | null;
  readonly loading: boolean;
  readonly error: string | null;
}

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

export const useMerchant = (id: string): UseMerchantResult => {
  const [state, setState] = useState<MerchantState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });

    const load = async (): Promise<void> => {
      try {
        const response = await fetch('/mocks/merchant.json');
        if (!response.ok) {
          throw new Error(`Failed to load merchant: ${String(response.status)}`);
        }
        const raw: unknown = await response.json();
        if (!isMerchant(raw)) {
          throw new Error('Merchant payload failed validation');
        }
        if (cancelled) return;
        setState({ status: 'ok', data: raw });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : 'Unknown error';
        setState({ status: 'error', error: message });
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [id]);

  if (state.status === 'loading') {
    return { data: null, loading: true, error: null };
  }
  if (state.status === 'error') {
    return { data: null, loading: false, error: state.error };
  }
  return { data: state.data, loading: false, error: null };
};
