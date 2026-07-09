import { describe, it, expect } from 'vitest';
import {
  INITIAL_DETAIL_STATE,
  detailReducer,
  type DetailState,
} from '../pages/MerchantDetailPage.reducer';
import type { Merchant } from '../types/merchant';

const sampleMerchant: Merchant = {
  id: 'stub-id-1',
  mccCode: '5943',
  transactionCount: 47,
  totalSpend: '3120.50',
  lines: [],
};

describe('detailReducer', () => {
  it('transitions idle -> loading on fetch/start', () => {
    const next = detailReducer(INITIAL_DETAIL_STATE, { type: 'fetch/start' });
    expect(next).toEqual({ status: 'loading' });
  });

  it('transitions loading -> success(entity) on fetch/success with merchant', () => {
    const loading: DetailState = { status: 'loading' };
    const next = detailReducer(loading, {
      type: 'fetch/success',
      payload: sampleMerchant,
    });
    expect(next).toEqual({ status: 'success', data: sampleMerchant });
  });

  it('transitions loading -> empty on fetch/success with null payload', () => {
    const loading: DetailState = { status: 'loading' };
    const next = detailReducer(loading, {
      type: 'fetch/success',
      payload: null,
    });
    expect(next).toEqual({ status: 'empty' });
  });

  it('transitions loading -> error on fetch/error', () => {
    const loading: DetailState = { status: 'loading' };
    const next = detailReducer(loading, {
      type: 'fetch/error',
      error: 'boom',
    });
    expect(next).toEqual({ status: 'error', error: 'boom' });
  });

  it('resets any state back to idle on reset', () => {
    const states: ReadonlyArray<DetailState> = [
      { status: 'loading' },
      { status: 'success', data: sampleMerchant },
      { status: 'error', error: 'boom' },
      { status: 'empty' },
    ];
    for (const s of states) {
      expect(detailReducer(s, { type: 'reset' })).toEqual(INITIAL_DETAIL_STATE);
    }
  });
});
