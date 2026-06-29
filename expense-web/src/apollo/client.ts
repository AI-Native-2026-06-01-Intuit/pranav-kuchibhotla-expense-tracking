import { ApolloClient, HttpLink, InMemoryCache, from } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';

// Threat model: JWT in localStorage is XSS-exposed. This is accepted only
// as a stopgap until HttpOnly cookie-based auth is added. Do not persist
// other sensitive material under the 'uc:jwt' key.
const JWT_STORAGE_KEY = 'uc:jwt';

const httpLink = new HttpLink({ uri: 'http://localhost:8080/graphql' });

const authLink = setContext((_operation, prevContext: { headers?: Record<string, string> }) => {
  const token = localStorage.getItem(JWT_STORAGE_KEY);
  const headers = prevContext.headers ?? {};
  if (token) {
    return { headers: { ...headers, authorization: `Bearer ${token}` } };
  }
  return { headers };
});

export const apolloClient = new ApolloClient({
  link: from([authLink, httpLink]),
  cache: new InMemoryCache({
    typePolicies: {
      Merchant: { keyFields: ['id'] },
    },
  }),
});
