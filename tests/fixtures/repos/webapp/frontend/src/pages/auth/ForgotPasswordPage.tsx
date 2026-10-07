import { useState } from 'react';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);

  return (
    <section>
      <h1>Reset your password</h1>
      {sent ? (
        <p>
          If {email.trim()} has an account, a code is on its way. It expires in 10 minutes.
        </p>
      ) : (
        <button onClick={() => setSent(true)}>Send code</button>
      )}
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
    </section>
  );
}
