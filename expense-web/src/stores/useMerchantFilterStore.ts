import { create } from 'zustand';
import { devtools, persist, createJSONStorage } from 'zustand/middleware';

interface FilterState {
  readonly mccFilter: ReadonlyArray<string>;
  readonly dateRange: readonly [string, string | null];
  readonly searchText: string;
  readonly includeArchived: boolean;
  readonly threshold: number;
}

interface FilterActions {
  readonly setMccFilter: (next: ReadonlyArray<string>) => void;
  readonly setSearchText: (next: string) => void;
  readonly setThreshold: (next: number) => void;
  readonly setIncludeArchived: (next: boolean) => void;
  readonly reset: () => void;
}

type Store = FilterState & FilterActions;

const initialState: FilterState = {
  mccFilter: [],
  dateRange: ['', null],
  searchText: '',
  includeArchived: false,
  threshold: 50,
};

export const useMerchantFilterStore = create<Store>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setMccFilter: (next) =>
          set({ mccFilter: next }, false, 'filters/setMccFilter'),
        setSearchText: (next) =>
          set({ searchText: next }, false, 'filters/setSearchText'),
        setThreshold: (next) =>
          set({ threshold: next }, false, 'filters/setThreshold'),
        setIncludeArchived: (next) =>
          set({ includeArchived: next }, false, 'filters/setIncludeArchived'),
        reset: () => set({ ...initialState }, false, 'filters/reset'),
      }),
      {
        name: 'expense-web:filters',
        storage: createJSONStorage(() => {
          // jsdom under Node 22+ omits localStorage; throwing here makes
          // zustand fall back to no-op storage so tests/SSR don't crash.
          if (typeof window === 'undefined' || window.localStorage === undefined) {
            throw new Error('localStorage unavailable');
          }
          return window.localStorage;
        }),
        // Only the threshold is persisted. Persisting searchText across reloads
        // would be a UX bug — users expect a fresh search box on each visit,
        // and a stale filter would silently hide results. mccFilter/dateRange/
        // includeArchived are session-scoped for the same reason.
        partialize: (state) => ({ threshold: state.threshold }),
      },
    ),
    { name: 'useMerchantFilterStore' },
  ),
);
