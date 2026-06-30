import type { ReactElement, ReactNode } from 'react';
import { render, type RenderOptions, type RenderResult } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

interface RenderWithProvidersOptions
  extends Omit<RenderOptions, 'wrapper' | 'queries'> {
  readonly route?: string;
  readonly apolloMocks?: ReadonlyArray<MockedResponse>;
  readonly queryClient?: QueryClient;
}

interface RenderWithProvidersResult extends RenderResult {
  readonly user: UserEvent;
  readonly queryClient: QueryClient;
}

const makeQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });

export const renderWithProviders = (
  ui: ReactElement,
  options: RenderWithProvidersOptions = {},
): RenderWithProvidersResult => {
  const {
    route = '/',
    apolloMocks = [],
    queryClient = makeQueryClient(),
    ...rest
  } = options;

  const user = userEvent.setup();

  const Wrapper = ({ children }: { readonly children: ReactNode }) => (
    <MockedProvider mocks={[...apolloMocks]}>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    </MockedProvider>
  );

  const renderResult = render(ui, { wrapper: Wrapper, ...rest });

  return { ...renderResult, user, queryClient };
};
