import { useEffect, useState } from 'react';
import { loadNamespace } from './index';

export function useLoadNs(ns: 'result' | 'knowledge') {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    loadNamespace(ns).then(() => setReady(true));
  }, [ns]);
  return ready;
}
