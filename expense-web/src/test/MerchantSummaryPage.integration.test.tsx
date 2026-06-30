// @vitest-environment happy-dom
import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import MerchantSummaryPage from '../pages/MerchantSummaryPage';
import { server } from './server';
import { summarizeMerchantError } from './handlers';
import { renderWithApolloHttp } from './renderWithApolloHttp';

const MERCHANT_ID = 'stub-1';
const ROUTE_AT = `/merchants/${MERCHANT_ID}/summary`;

const renderPage = () =>
  renderWithApolloHttp(
    <Routes>
      <Route
        path="/merchants/:id/summary"
        element={<MerchantSummaryPage />}
      />
    </Routes>,
    { route: ROUTE_AT },
  );

describe('MerchantSummaryPage (integration via MSW + HttpLink)', () => {
  it('shows the optimistic "...thinking..." placeholder while the real MSW response is in flight', async () => {
    const { user } = renderPage();
    await user.click(screen.getByRole('button', { name: /summarize/i }));
    expect(await screen.findByText('...thinking...')).toBeInTheDocument();
  });

  it('renders the final stubbed summary text from MSW after the mutation resolves', async () => {
    const { user } = renderPage();
    await user.click(screen.getByRole('button', { name: /summarize/i }));
    await waitFor(() => {
      expect(screen.getByText('stub summary from MSW')).toBeInTheDocument();
    });
    expect(screen.getByText(/confidence: HIGH/i)).toBeInTheDocument();
  });

  it('surfaces a role="alert" when MSW returns a GraphQL mutation error', async () => {
    server.use(summarizeMerchantError('summarize boom'));
    const { user } = renderPage();
    await user.click(screen.getByRole('button', { name: /summarize/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/boom/i);
  });
});
