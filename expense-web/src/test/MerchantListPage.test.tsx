import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ApolloProvider, ApolloClient, InMemoryCache, HttpLink } from '@apollo/client';
import { MemoryRouter } from 'react-router-dom';
import MerchantListPage from '../pages/MerchantListPage';

const makeClient = () =>
  new ApolloClient({
    link: new HttpLink({ uri: 'http://localhost:8080/graphql', fetch }),
    cache: new InMemoryCache({ typePolicies: { Merchant: { keyFields: ['id'] } } }),
  });

const renderPage = () =>
  render(
    <ApolloProvider client={makeClient()}>
      <MemoryRouter>
        <MerchantListPage />
      </MemoryRouter>
    </ApolloProvider>,
  );

describe('MerchantListPage', () => {
  beforeEach(() => { window.localStorage.clear(); });

  it('renders three merchants from MSW', async () => {
    renderPage();
    const list = await screen.findByLabelText('merchant-list');
    const items = list.querySelectorAll('li');
    expect(items).toHaveLength(3);
  });

  it('shows the merchant name "stub one"', async () => {
    renderPage();
    expect(await screen.findByText('stub one')).toBeInTheDocument();
  });
});
