import { describe, it, expect } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useGetExpenseTrackingRest } from '../hooks/useGetExpenseTrackingRest';
import { server } from './server';
import { restMerchantError, restMerchantHappy } from './handlers';

const wrapperFor = (client: QueryClient) => {
  const Wrapper = ({ children }: { readonly children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

const freshClient = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });

describe('useGetExpenseTrackingRest (integration via MSW)', () => {
  it('resolves with the stub merchant from the default REST happy path', async () => {
    const { result } = renderHook(() => useGetExpenseTrackingRest('stub-1'), {
      wrapper: wrapperFor(freshClient()),
    });
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });
    expect(result.current.data).toEqual({
      id: 'stub-1',
      name: 'stub merchant',
      updatedAt: '2025-01-04T00:00:00Z',
    });
  });

  it('exposes isError and "HTTP 500" message when MSW returns 500', async () => {
    server.use(restMerchantError(500));
    const { result } = renderHook(() => useGetExpenseTrackingRest('stub-1'), {
      wrapper: wrapperFor(freshClient()),
    });
    await waitFor(() => {
      expect(result.current.isError).toBe(true);
    });
    expect(result.current.error?.message).toBe('HTTP 500');
  });

  it('stays idle (no fetch fires) when id is empty', () => {
    const { result } = renderHook(() => useGetExpenseTrackingRest(''), {
      wrapper: wrapperFor(freshClient()),
    });
    expect(result.current.fetchStatus).toBe('idle');
    expect(result.current.status).toBe('pending');
  });

  it('reuses the cached value across remount when the QueryClient is shared', async () => {
    const client = freshClient();
    const wrapper = wrapperFor(client);

    const first = renderHook(() => useGetExpenseTrackingRest('stub-42'), {
      wrapper,
    });
    await waitFor(() => {
      expect(first.result.current.isSuccess).toBe(true);
    });
    expect(first.result.current.data?.id).toBe('stub-42');

    // Swap the handler to a 500. If the cache is reused, the second mount
    // must short-circuit and surface the original payload without hitting MSW.
    server.use(restMerchantError(500));
    const second = renderHook(() => useGetExpenseTrackingRest('stub-42'), {
      wrapper,
    });

    expect(second.result.current.data?.id).toBe('stub-42');
    expect(second.result.current.isError).toBe(false);
  });

  it('passes a custom payload through when handler is overridden with restMerchantHappy', async () => {
    server.use(restMerchantHappy({ name: 'custom merchant' }));
    const { result } = renderHook(() => useGetExpenseTrackingRest('mid-1'), {
      wrapper: wrapperFor(freshClient()),
    });
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });
    expect(result.current.data?.name).toBe('custom merchant');
    expect(result.current.data?.id).toBe('mid-1');
  });
});
