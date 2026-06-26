import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MerchantDetailPage from '../pages/MerchantDetailPage';
import { useMerchantFilterStore } from '../stores/useMerchantFilterStore';

const merchantStub = {
  id: 'stub-id-1',
  mccCode: '5943',
  transactionCount: 47,
  totalSpend: '3120.50',
  lines: [
    { id: 'line-1', amount: '100.00' },
    { id: 'line-2', amount: '250.00' },
  ],
};

const stubFetch = () => {
  const fetchMock = vi.fn(
    () =>
      Promise.resolve(
        new Response(JSON.stringify(merchantStub), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};

describe('MerchantDetailPage', () => {
  beforeEach(() => {
    window.localStorage.clear();
    useMerchantFilterStore.setState(
      useMerchantFilterStore.getInitialState(),
      true,
    );
    stubFetch();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders merchant heading and mccCode from the stub payload', async () => {
    render(<MerchantDetailPage />);

    const heading = await screen.findByRole('heading', { level: 1 });
    expect(heading).toHaveTextContent('stub-id-1');
    expect(screen.getByText('5943')).toBeInTheDocument();
  });

  it('updates readout to 51% when ArrowRight is pressed on the slider', async () => {
    const user = userEvent.setup();
    render(<MerchantDetailPage />);

    await screen.findByRole('heading', { level: 1 });

    const slider = screen.getByLabelText('Threshold');
    slider.focus();
    await user.keyboard('{ArrowRight}');

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Threshold: 51%');
    });
  });
});
