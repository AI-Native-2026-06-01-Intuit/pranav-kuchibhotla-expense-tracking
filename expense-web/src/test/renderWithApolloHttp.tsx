import type { ReactElement, ReactNode } from 'react';
import { render, type RenderOptions, type RenderResult } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import {
  ApolloClient,
  ApolloProvider,
  HttpLink,
  InMemoryCache,
} from '@apollo/client';
import { MemoryRouter } from 'react-router-dom';

interface RenderWithApolloHttpOptions
  extends Omit<RenderOptions, 'wrapper' | 'queries'> {
  readonly route?: string;
  readonly uri?: string;
  readonly cache?: InMemoryCache;
}

interface RenderWithApolloHttpResult extends RenderResult {
  readonly user: UserEvent;
  readonly client: ApolloClient<unknown>;
}

const DEFAULT_URI = 'http://localhost:8080/graphql';

const makeCache = (): InMemoryCache =>
  new InMemoryCache({ typePolicies: { Merchant: { keyFields: ['id'] } } });

export const renderWithApolloHttp = (
  ui: ReactElement,
  options: RenderWithApolloHttpOptions = {},
): RenderWithApolloHttpResult => {
  const { route = '/', uri = DEFAULT_URI, cache = makeCache(), ...rest } = options;

  const client = new ApolloClient({
    link: new HttpLink({ uri, fetch }),
    cache,
    defaultOptions: {
      watchQuery: { fetchPolicy: 'no-cache' },
      query: { fetchPolicy: 'no-cache' },
    },
  });

  const user = userEvent.setup();

  const Wrapper = ({ children }: { readonly children: ReactNode }) => (
    <ApolloProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
    </ApolloProvider>
  );

  const renderResult = render(ui, { wrapper: Wrapper, ...rest });
  return { ...renderResult, user, client };
};
