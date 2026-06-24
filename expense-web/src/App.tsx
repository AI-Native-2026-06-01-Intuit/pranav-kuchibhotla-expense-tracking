import { useEffect, useState } from 'react';
import MerchantDetailPage from './pages/MerchantDetailPage';

const MERCHANT_ROUTE = '#/merchants/stub-id-1';

const App = () => {
  const [hash, setHash] = useState<string>(window.location.hash);

  useEffect(() => {
    const handler = () => { setHash(window.location.hash); };
    window.addEventListener('hashchange', handler);
    return () => { window.removeEventListener('hashchange', handler); };
  }, []);

  if (hash === MERCHANT_ROUTE) {
    return <MerchantDetailPage />;
  }

  return (
    <main>
      <h1>Expense Web</h1>
      <p>
        <a href={MERCHANT_ROUTE}>Open merchant stub-id-1</a>
      </p>
    </main>
  );
};

export default App;
