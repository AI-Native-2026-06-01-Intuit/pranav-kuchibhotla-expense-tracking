import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RouterProvider } from 'react-router-dom';
import { ApolloProvider, ApolloClient, InMemoryCache, HttpLink } from '@apollo/client';
import { createAppRouter } from '../router';

const makeClient = () =>
  new ApolloClient({
    link: new HttpLink({ uri: 'http://localhost:8080/graphql', fetch }),
    cache: new InMemoryCache(),
  });

const renderRouterAt = (path: string) => {
  const router = createAppRouter([path]);
  return render(
    <ApolloProvider client={makeClient()}>
      <RouterProvider router={router} />
    </ApolloProvider>,
  );
};

describe('ProtectedLayout', () => {
  beforeEach(() => { window.localStorage.clear(); });

  it('redirects to /login when no JWT is in localStorage', async () => {
    renderRouterAt('/merchants');
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders the protected child when JWT is present', async () => {
    window.localStorage.setItem('uc:jwt', 'stub.jwt.token');
    renderRouterAt('/merchants');
    expect(await screen.findByLabelText('merchant-list')).toBeInTheDocument();
  });
});
