import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApolloProvider, ApolloClient, InMemoryCache, HttpLink } from '@apollo/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import MerchantSummaryPage from '../pages/MerchantSummaryPage';

const makeClient = () =>
  new ApolloClient({
    link: new HttpLink({ uri: 'http://localhost:8080/graphql', fetch }),
    cache: new InMemoryCache(),
  });

const renderAt = (path: string) =>
  render(
    <ApolloProvider client={makeClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/merchants/:id/summary" element={<MerchantSummaryPage />} />
        </Routes>
      </MemoryRouter>
    </ApolloProvider>,
  );

describe('MerchantSummaryPage', () => {
  beforeEach(() => { window.localStorage.clear(); });

  it('shows optimistic placeholder then real summary on Summarize click', async () => {
    const user = userEvent.setup();
    renderAt('/merchants/stub-1/summary');

    await user.click(screen.getByRole('button', { name: /summarize/i }));

    expect(await screen.findByText('...thinking...')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('stub summary from MSW')).toBeInTheDocument();
    });
  });

  it('renders the merchant id from the route param in the heading', async () => {
    renderAt('/merchants/stub-1/summary');
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('stub-1');
  });
});
