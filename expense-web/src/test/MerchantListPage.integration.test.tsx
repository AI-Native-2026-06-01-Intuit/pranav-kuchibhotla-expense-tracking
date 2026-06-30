// @vitest-environment happy-dom
import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import MerchantListPage from '../pages/MerchantListPage';
import { server } from './server';
import {
  latestMerchantsEmpty,
  latestMerchantsError,
  latestMerchantsSlow,
} from './handlers';
import { renderWithApolloHttp } from './renderWithApolloHttp';

describe('MerchantListPage (integration via MSW + HttpLink)', () => {
  it('renders three merchants from the default MSW happy path', async () => {
    renderWithApolloHttp(<MerchantListPage />);
    const list = await screen.findByRole('list', { name: /merchant-list/i });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
  });

  it('renders the first merchant by accessible link name through MSW', async () => {
    renderWithApolloHttp(<MerchantListPage />);
    expect(
      await screen.findByRole('link', { name: 'stub one' }),
    ).toHaveAttribute('href', '/merchants/stub-1');
  });

  it('shows the empty-state message when MSW returns no merchants', async () => {
    server.use(latestMerchantsEmpty());
    renderWithApolloHttp(<MerchantListPage />);
    expect(await screen.findByText(/no merchants yet/i)).toBeInTheDocument();
  });

  it('surfaces role="alert" when MSW returns a GraphQL error', async () => {
    server.use(latestMerchantsError('latestMerchants exploded'));
    renderWithApolloHttp(<MerchantListPage />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/exploded/i);
  });

  it('renders role="status" loader before slow MSW response resolves', async () => {
    server.use(latestMerchantsSlow(80));
    renderWithApolloHttp(<MerchantListPage />);
    expect(screen.getByRole('status')).toHaveTextContent(/loading merchants/i);
    await screen.findByRole('list', { name: /merchant-list/i });
  });
});
