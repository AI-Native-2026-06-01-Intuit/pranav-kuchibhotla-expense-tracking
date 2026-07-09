import { describe, it, expect } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useGetExpenseTrackingRest } from '../hooks/useGetExpenseTrackingRest';

const wrapperFor = (client: QueryClient) => {
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

const freshClient = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false } } });

describe('useGetExpenseTrackingRest', () => {
  it('returns the stubbed merchant for a non-empty id', async () => {
    const { result } = renderHook(() => useGetExpenseTrackingRest('stub-1'), {
      wrapper: wrapperFor(freshClient()),
    });

    await waitFor(() => { expect(result.current.isSuccess).toBe(true); });
    expect(result.current.data?.name).toBe('stub merchant');
    expect(result.current.data?.id).toBe('stub-1');
  });

  it('does not fire when id is empty (enabled gate)', () => {
    const { result } = renderHook(() => useGetExpenseTrackingRest(''), {
      wrapper: wrapperFor(freshClient()),
    });
    expect(result.current.fetchStatus).toBe('idle');
  });
});
