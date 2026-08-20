import { useEffect, useState } from 'react';

import { fetchHealth } from './health';

const API_URL = import.meta.env['VITE_API_URL'] ?? 'http://127.0.0.1:8000';

export function App() {
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let live = true;
    void fetchHealth(API_URL).then((result) => {
      if (live) setHealthy(result);
    });
    return () => {
      live = false;
    };
  }, []);

  return (
    <main>
      <h1>__PROJECT__</h1>
      <p>API: {healthy === null ? 'checking…' : healthy ? 'up' : 'unreachable'}</p>
    </main>
  );
}
