import { useNavigate } from 'react-router-dom';

const JWT_STORAGE_KEY = 'uc:jwt';
const STUB_JWT = 'stub.jwt.token';

const LoginPage = () => {
  const navigate = useNavigate();

  const onSignIn = () => {
    localStorage.setItem(JWT_STORAGE_KEY, STUB_JWT);
    void navigate('/merchants');
  };

  return (
    <main aria-label="login">
      <h1>Sign in</h1>
      <button onClick={onSignIn}>Sign in (stub)</button>
    </main>
  );
};

export default LoginPage;
