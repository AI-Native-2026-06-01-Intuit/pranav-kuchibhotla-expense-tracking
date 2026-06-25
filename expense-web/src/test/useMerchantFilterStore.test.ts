import { describe, it, expect, beforeEach } from 'vitest';
import { useMerchantFilterStore } from '../stores/useMerchantFilterStore';

describe('useMerchantFilterStore', () => {
  beforeEach(() => {
    window.localStorage.clear();
    useMerchantFilterStore.setState(
      useMerchantFilterStore.getInitialState(),
      true,
    );
  });

  it('setSearchText updates state.searchText', () => {
    useMerchantFilterStore.getState().setSearchText('foo');
    expect(useMerchantFilterStore.getState().searchText).toBe('foo');
  });

  it('setThreshold updates state.threshold', () => {
    useMerchantFilterStore.getState().setThreshold(80);
    expect(useMerchantFilterStore.getState().threshold).toBe(80);
  });

  it('setMccFilter replaces the previous list', () => {
    useMerchantFilterStore.getState().setMccFilter(['A', 'B']);
    useMerchantFilterStore.getState().setMccFilter(['C']);
    expect(useMerchantFilterStore.getState().mccFilter).toEqual(['C']);
  });

  it('reset returns state to initial shape', () => {
    const { setSearchText, setThreshold, setMccFilter, setIncludeArchived } =
      useMerchantFilterStore.getState();
    setSearchText('dirty');
    setThreshold(7);
    setMccFilter(['X']);
    setIncludeArchived(true);

    useMerchantFilterStore.getState().reset();

    const s = useMerchantFilterStore.getState();
    expect(s.searchText).toBe('');
    expect(s.threshold).toBe(50);
    expect(s.mccFilter).toEqual([]);
    expect(s.includeArchived).toBe(false);
    expect(s.dateRange).toEqual(['', null]);
  });
});
