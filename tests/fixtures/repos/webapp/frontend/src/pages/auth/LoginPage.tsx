import { useState } from 'react';
import { EmailNotVerifiedError, login, parseApiError } from '../../api/auth';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const submit = async () => {
    try {
      await login(email, password);
    } catch (err) {
      if (err instanceof EmailNotVerifiedError) {
        setError('Please verify your email first.');
        return;
      }
      setError(parseApiError(err).message);
    }
  };

  return (
    <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      {error && <p role="alert">{error}</p>}
      <button type="submit">Sign in</button>
    </form>
  );
}
