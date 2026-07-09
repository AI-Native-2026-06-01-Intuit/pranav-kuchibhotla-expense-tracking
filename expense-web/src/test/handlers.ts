import { HttpResponse, delay, graphql, http } from 'msw';
import { GraphQLError } from 'graphql';
import { sseHandlers } from './sse-handlers';

type SummarizeVars = { id: string };

export interface MerchantStub {
  readonly __typename: 'Merchant';
  readonly id: string;
  readonly name: string;
  readonly updatedAt: string;
}

export const DEFAULT_LATEST_MERCHANTS: ReadonlyArray<MerchantStub> = [
  { __typename: 'Merchant', id: 'stub-1', name: 'stub one', updatedAt: '2025-01-01T00:00:00Z' },
  { __typename: 'Merchant', id: 'stub-2', name: 'stub two', updatedAt: '2025-01-02T00:00:00Z' },
  { __typename: 'Merchant', id: 'stub-3', name: 'stub three', updatedAt: '2025-01-03T00:00:00Z' },
];

export const latestMerchantsHappy = (
  merchants: ReadonlyArray<MerchantStub> = DEFAULT_LATEST_MERCHANTS,
) =>
  graphql.query('LatestMerchants', () =>
    HttpResponse.json({ data: { latestMerchants: [...merchants] } }),
  );

export const latestMerchantsEmpty = () =>
  graphql.query('LatestMerchants', () =>
    HttpResponse.json({ data: { latestMerchants: [] } }),
  );

export const latestMerchantsError = (message = 'latestMerchants exploded') =>
  graphql.query('LatestMerchants', () =>
    HttpResponse.json({
      errors: [new GraphQLError(message)],
    }),
  );

export const latestMerchantsSlow = (
  delayMs: number,
  merchants: ReadonlyArray<MerchantStub> = DEFAULT_LATEST_MERCHANTS,
) =>
  graphql.query('LatestMerchants', async () => {
    await delay(delayMs);
    return HttpResponse.json({ data: { latestMerchants: [...merchants] } });
  });

export const summarizeMerchantHappy = (delayMs = 50) =>
  graphql.mutation<{ summarizeMerchant: unknown }, SummarizeVars>(
    'SummarizeMerchant',
    async ({ variables }) => {
      // Small delay so the Apollo optimistic response is observable in tests
      // before the real MSW response replaces it.
      await delay(delayMs);
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
  );

export const summarizeMerchantError = (message = 'summarize boom') =>
  graphql.mutation<{ summarizeMerchant: unknown }, SummarizeVars>(
    'SummarizeMerchant',
    () =>
      HttpResponse.json({
        errors: [new GraphQLError(message)],
      }),
  );

export interface MerchantRestPayload {
  readonly id: string;
  readonly name: string;
  readonly updatedAt: string;
}

export const restMerchantHappy = (
  payload: Partial<MerchantRestPayload> = {},
) =>
  http.get('http://localhost:8080/api/v1/merchants/:id', ({ params }) =>
    HttpResponse.json({
      id: payload.id ?? params.id,
      name: payload.name ?? 'stub merchant',
      updatedAt: payload.updatedAt ?? '2025-01-04T00:00:00Z',
    }),
  );

export const restMerchantError = (status = 500) =>
  http.get('http://localhost:8080/api/v1/merchants/:id', () =>
    HttpResponse.json({ message: 'kaboom' }, { status }),
  );

export const restMerchantSlow = (
  delayMs: number,
  payload: Partial<MerchantRestPayload> = {},
) =>
  http.get('http://localhost:8080/api/v1/merchants/:id', async ({ params }) => {
    await delay(delayMs);
    return HttpResponse.json({
      id: payload.id ?? params.id,
      name: payload.name ?? 'stub merchant',
      updatedAt: payload.updatedAt ?? '2025-01-04T00:00:00Z',
    });
  });

export const handlers = [
  latestMerchantsHappy(),
  summarizeMerchantHappy(),
  restMerchantHappy(),
  ...sseHandlers,
];
