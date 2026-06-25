import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useDebouncedSearch } from '../hooks/useDebouncedSearch';
import { useMerchantFilterStore } from '../stores/useMerchantFilterStore';

describe('useDebouncedSearch', () => {
  beforeEach(() => {
    if (typeof window !== 'undefined' && window.localStorage !== undefined) {
      window.localStorage.clear();
    }
    useMerchantFilterStore.setState(
      useMerchantFilterStore.getInitialState(),
      true,
    );
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('lags the source by delayMs', () => {
    const { result } = renderHook(() => useDebouncedSearch(300));
    expect(result.current).toBe('');

    act(() => {
      useMerchantFilterStore.getState().setSearchText('foo');
    });
    expect(result.current).toBe('');

    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(result.current).toBe('');

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe('foo');
  });

  it('cancels a pending write when the source changes mid-flight', () => {
    const { result } = renderHook(() => useDebouncedSearch(300));

    act(() => {
      useMerchantFilterStore.getState().setSearchText('foo');
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(result.current).toBe('');

    act(() => {
      useMerchantFilterStore.getState().setSearchText('foobar');
    });
    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(result.current).toBe('');

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe('foobar');
  });
});
