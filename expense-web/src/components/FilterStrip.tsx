import { useMerchantFilterStore } from '../stores/useMerchantFilterStore';

const FilterStrip = () => {
  const mccFilter = useMerchantFilterStore((s) => s.mccFilter);
  const setMccFilter = useMerchantFilterStore((s) => s.setMccFilter);
  const dateRange = useMerchantFilterStore((s) => s.dateRange);
  const searchText = useMerchantFilterStore((s) => s.searchText);
  const setSearchText = useMerchantFilterStore((s) => s.setSearchText);
  const includeArchived = useMerchantFilterStore((s) => s.includeArchived);
  const setIncludeArchived = useMerchantFilterStore((s) => s.setIncludeArchived);

  const handleMccChange = (raw: string): void => {
    const next = raw
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    setMccFilter(next);
  };

  const [from, to] = dateRange;

  return (
    <section aria-label="Filters">
      <label>
        MCC filter
        <input
          type="text"
          aria-label="MCC filter"
          placeholder="e.g. 5943, 5812"
          value={mccFilter.join(', ')}
          onChange={(e) => { handleMccChange(e.currentTarget.value); }}
        />
      </label>
      <label>
        Date range
        <span aria-label="Date range">
          {from === '' ? '—' : from} → {to ?? '—'}
        </span>
      </label>
      <label>
        Search
        <input
          type="search"
          aria-label="Search"
          value={searchText}
          onChange={(e) => { setSearchText(e.currentTarget.value); }}
        />
      </label>
      <label>
        <input
          type="checkbox"
          aria-label="Include archived"
          checked={includeArchived}
          onChange={(e) => { setIncludeArchived(e.currentTarget.checked); }}
        />
        Include archived
      </label>
    </section>
  );
};

export default FilterStrip;
