import { useState } from 'react';
import { verifyEmail } from '../../api/auth';

export default function VerifyEmailPage({ email }: { email: string }) {
  const [code, setCode] = useState('');

  return (
    <section>
      <h1>Check your inbox</h1>
      <p>
        Enter the 6-digit code we sent to <strong>{email}</strong>. It expires in 10 minutes.
      </p>
      <input value={code} onChange={(e) => setCode(e.target.value)} />
      <button onClick={() => verifyEmail(email, code)}>Verify</button>
    </section>
  );
}
