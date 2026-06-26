import type { Merchant } from '../types/merchant';

export type DetailState =
  | { readonly status: 'idle' }
  | { readonly status: 'loading' }
  | { readonly status: 'success'; readonly data: Merchant }
  | { readonly status: 'error'; readonly error: string }
  | { readonly status: 'empty' };

export type DetailAction =
  | { readonly type: 'fetch/start' }
  | { readonly type: 'fetch/success'; readonly payload: Merchant | null }
  | { readonly type: 'fetch/error'; readonly error: string }
  | { readonly type: 'reset' };

export const INITIAL_DETAIL_STATE: DetailState = { status: 'idle' };

export const detailReducer = (
  _state: DetailState,
  action: DetailAction,
): DetailState => {
  switch (action.type) {
    case 'fetch/start':
      return { status: 'loading' };
    case 'fetch/success':
      return action.payload === null
        ? { status: 'empty' }
        : { status: 'success', data: action.payload };
    case 'fetch/error':
      return { status: 'error', error: action.error };
    case 'reset':
      return INITIAL_DETAIL_STATE;
    default: {
      const _exhaustive: never = action;
      return _exhaustive;
    }
  }
};
