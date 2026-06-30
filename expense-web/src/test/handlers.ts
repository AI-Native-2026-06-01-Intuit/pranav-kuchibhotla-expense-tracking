import { HttpResponse, delay, graphql, http } from 'msw';
import { sseHandlers } from './sse-handlers';

type SummarizeVars = { id: string };

export const handlers = [
  graphql.query('LatestMerchants', () =>
    HttpResponse.json({
      data: {
        latestMerchants: [
          { __typename: 'Merchant', id: 'stub-1', name: 'stub one', updatedAt: '2025-01-01T00:00:00Z' },
          { __typename: 'Merchant', id: 'stub-2', name: 'stub two', updatedAt: '2025-01-02T00:00:00Z' },
          { __typename: 'Merchant', id: 'stub-3', name: 'stub three', updatedAt: '2025-01-03T00:00:00Z' },
        ],
      },
    }),
  ),

  graphql.mutation<{ summarizeMerchant: unknown }, SummarizeVars>(
    'SummarizeMerchant',
    async ({ variables }) => {
      // Small delay so the Apollo optimistic response is observable in tests
      // before the real MSW response replaces it.
      await delay(50);
      return HttpResponse.json({
        data: {
          summarizeMerchant: {
            __typename: 'MerchantSummary',
            id: variables.id,
            summaryText: 'stub summary from MSW',
            confidence: 'HIGH',
          },
        },
      });
    },
  ),

  http.get('http://localhost:8080/api/v1/merchants/:id', ({ params }) =>
    HttpResponse.json({
      id: params.id,
      name: 'stub merchant',
      updatedAt: '2025-01-04T00:00:00Z',
    }),
  ),

  ...sseHandlers,
];
