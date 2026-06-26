import { useEffect, useState } from 'react';
import { useMerchantFilterStore } from '../stores/useMerchantFilterStore';

export const useDebouncedSearch = (delayMs = 300): string => {
  const searchText = useMerchantFilterStore((s) => s.searchText);
  const [debounced, setDebounced] = useState<string>(searchText);

  useEffect(() => {
    const timer = setTimeout(() => { setDebounced(searchText); }, delayMs);
    return () => { clearTimeout(timer); };
  }, [searchText, delayMs]);

  return debounced;
};
