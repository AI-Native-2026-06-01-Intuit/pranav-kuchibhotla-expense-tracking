import { describe, it, expect, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import FilterStrip from '../components/FilterStrip';
import { useMerchantFilterStore } from '../stores/useMerchantFilterStore';
import { renderWithProviders } from './renderWithProviders';

describe('FilterStrip + useMerchantFilterStore (integration)', () => {
  beforeEach(() => {
    useMerchantFilterStore.getState().reset();
  });

  it('writes typed search text into the store as the user types', async () => {
    const { user } = renderWithProviders(<FilterStrip />);
    const search = screen.getByRole('searchbox', { name: /search/i });
    await user.type(search, 'coffee');
    expect(useMerchantFilterStore.getState().searchText).toBe('coffee');
    expect(search).toHaveValue('coffee');
  });

  it('parses a comma-separated MCC list into the store array', async () => {
    const { user } = renderWithProviders(<FilterStrip />);
    const mcc = screen.getByRole('textbox', { name: /mcc filter/i });
    // Paste avoids the controlled-input churn that key-by-key typing
    // causes when the store re-joins the array on every keystroke.
    await user.click(mcc);
    await user.paste('5943, 5812');
    expect(useMerchantFilterStore.getState().mccFilter).toEqual([
      '5943',
      '5812',
    ]);
  });

  it('toggles includeArchived through the checkbox', async () => {
    const { user } = renderWithProviders(<FilterStrip />);
    const checkbox = screen.getByRole('checkbox', { name: /include archived/i });
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(useMerchantFilterStore.getState().includeArchived).toBe(true);
  });
});
