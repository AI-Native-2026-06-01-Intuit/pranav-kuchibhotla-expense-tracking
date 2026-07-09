import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { Route, Routes } from 'react-router-dom';
import type { MockedResponse } from '@apollo/client/testing';
import { SummarizeMerchantDocument } from '../gql/generated/graphql';
import MerchantSummaryPage from '../pages/MerchantSummaryPage';
import { renderWithProviders } from './renderWithProviders';

const MERCHANT_ID = 'stub-1';
const ROUTE_PATH = '/merchants/:id/summary';
const ROUTE_AT = `/merchants/${MERCHANT_ID}/summary`;

const summaryMock = (delay = 50): MockedResponse => ({
  request: {
    query: SummarizeMerchantDocument,
    variables: { id: MERCHANT_ID },
  },
  delay,
  result: {
    data: {
      summarizeMerchant: {
        __typename: 'MerchantSummary',
        id: MERCHANT_ID,
        summaryText: 'stub summary from MSW',
        confidence: 'HIGH',
      },
    },
  },
});

const errorSummaryMock: MockedResponse = {
  request: {
    query: SummarizeMerchantDocument,
    variables: { id: MERCHANT_ID },
  },
  error: new Error('mutation boom'),
};

const renderPage = (apolloMocks: ReadonlyArray<MockedResponse>) =>
  renderWithProviders(
    <Routes>
      <Route path={ROUTE_PATH} element={<MerchantSummaryPage />} />
    </Routes>,
    { route: ROUTE_AT, apolloMocks },
  );

describe('MerchantSummaryPage', () => {
  it('renders the merchant id from the route param in the heading', () => {
    renderPage([summaryMock()]);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      MERCHANT_ID,
    );
  });

  it('exposes a Summarize button by accessible name', () => {
    renderPage([summaryMock()]);
    expect(
      screen.getByRole('button', { name: /summarize/i }),
    ).toBeInTheDocument();
  });

  it('shows the optimistic "...thinking..." placeholder after click', async () => {
    const { user } = renderPage([summaryMock()]);
    await user.click(screen.getByRole('button', { name: /summarize/i }));
    expect(await screen.findByText('...thinking...')).toBeInTheDocument();
  });

  it('replaces the placeholder with the final summary text', async () => {
    const { user } = renderPage([summaryMock()]);
    await user.click(screen.getByRole('button', { name: /summarize/i }));
    await waitFor(() => {
      expect(screen.getByText('stub summary from MSW')).toBeInTheDocument();
    });
  });

  it('shows the resolved confidence value after the mutation resolves', async () => {
    const { user } = renderPage([summaryMock()]);
    await user.click(screen.getByRole('button', { name: /summarize/i }));
    await waitFor(() => {
      expect(screen.getByText(/confidence: HIGH/i)).toBeInTheDocument();
    });
  });

  it('disables the Summarize button while the mutation is in flight', async () => {
    const { user } = renderPage([summaryMock(80)]);
    const button = screen.getByRole('button', { name: /summarize/i });
    await user.click(button);
    await waitFor(() => {
      expect(button).toBeDisabled();
    });
  });

  it('surfaces a role="alert" when the mutation errors', async () => {
    const { user } = renderPage([errorSummaryMock]);
    await user.click(screen.getByRole('button', { name: /summarize/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/boom/i);
  });

  it('renders a link to the merchant chat route', () => {
    renderPage([summaryMock()]);
    const link = screen.getByRole('link', { name: /open chat for this merchant/i });
    expect(link).toHaveAttribute('href', `/merchants/${MERCHANT_ID}/chat`);
  });

  it('has no detectable accessibility violations at rest', async () => {
    const { container } = renderPage([summaryMock()]);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
