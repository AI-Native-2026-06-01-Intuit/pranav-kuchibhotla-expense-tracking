import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import { axe } from 'jest-axe';
import type { MockedResponse } from '@apollo/client/testing';
import { LatestMerchantsDocument } from '../gql/generated/graphql';
import MerchantListPage from '../pages/MerchantListPage';
import { renderWithProviders } from './renderWithProviders';

interface Merchant {
  readonly __typename: 'Merchant';
  readonly id: string;
  readonly name: string;
  readonly updatedAt: string;
}

const THREE_MERCHANTS: ReadonlyArray<Merchant> = [
  { __typename: 'Merchant', id: 'stub-1', name: 'stub one', updatedAt: '2025-01-01T00:00:00Z' },
  { __typename: 'Merchant', id: 'stub-2', name: 'stub two', updatedAt: '2025-01-02T00:00:00Z' },
  { __typename: 'Merchant', id: 'stub-3', name: 'stub three', updatedAt: '2025-01-03T00:00:00Z' },
];

const successMock = (merchants: ReadonlyArray<Merchant>): MockedResponse => ({
  request: { query: LatestMerchantsDocument },
  result: { data: { latestMerchants: [...merchants] } },
});

const emptyMock: MockedResponse = {
  request: { query: LatestMerchantsDocument },
  result: { data: { latestMerchants: [] } },
};

const errorMock: MockedResponse = {
  request: { query: LatestMerchantsDocument },
  error: new Error('boom'),
};

describe('MerchantListPage', () => {
  it('shows a loading status while the query is in flight', () => {
    renderWithProviders(<MerchantListPage />, {
      apolloMocks: [successMock(THREE_MERCHANTS)],
    });
    expect(screen.getByRole('status')).toHaveTextContent(/loading merchants/i);
  });

  it('renders the merchant list once data resolves', async () => {
    renderWithProviders(<MerchantListPage />, {
      apolloMocks: [successMock(THREE_MERCHANTS)],
    });
    const list = await screen.findByRole('list', { name: /merchant-list/i });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
  });

  it('shows the first merchant by its accessible link name', async () => {
    renderWithProviders(<MerchantListPage />, {
      apolloMocks: [successMock(THREE_MERCHANTS)],
    });
    const link = await screen.findByRole('link', { name: 'stub one' });
    expect(link).toBeInTheDocument();
  });

  it('points each link at /merchants/:id', async () => {
    renderWithProviders(<MerchantListPage />, {
      apolloMocks: [successMock(THREE_MERCHANTS)],
    });
    const link = await screen.findByRole('link', { name: 'stub one' });
    expect(link).toHaveAttribute('href', '/merchants/stub-1');
  });

  it('renders one link per merchant in resolved order', async () => {
    renderWithProviders(<MerchantListPage />, {
      apolloMocks: [successMock(THREE_MERCHANTS)],
    });
    await screen.findByRole('link', { name: 'stub one' });
    const links = screen.getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '/merchants/stub-1',
      '/merchants/stub-2',
      '/merchants/stub-3',
    ]);
  });

  it('shows an empty-state message when the server returns no merchants', async () => {
    renderWithProviders(<MerchantListPage />, { apolloMocks: [emptyMock] });
    expect(await screen.findByText(/no merchants yet/i)).toBeInTheDocument();
  });

  it('surfaces a role="alert" when the query errors', async () => {
    renderWithProviders(<MerchantListPage />, { apolloMocks: [errorMock] });
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('has no detectable accessibility violations on the happy path', async () => {
    const { container } = renderWithProviders(<MerchantListPage />, {
      apolloMocks: [successMock(THREE_MERCHANTS)],
    });
    await screen.findByRole('list', { name: /merchant-list/i });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
