import { useCallback, useEffect, useRef, useState } from "react";
import type { Status } from "../api/types";
import { api } from "../api/client";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Fetch data, re-running when deps change and (optionally) on an interval. */
export function useApiData<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
  intervalMs?: number,
): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef<() => Promise<T>>(fn);
  fnRef.current = fn;

  useEffect(() => {
    let active = true;
    setLoading(true);
    const run = () =>
      fnRef
        .current()
        .then((d) => {
          if (active) {
            setData(d);
            setError(null);
          }
        })
        .catch((e: unknown) => {
          if (active) setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    run();
    if (intervalMs && intervalMs > 0) {
      const id = setInterval(run, intervalMs);
      return () => {
        active = false;
        clearInterval(id);
      };
    }
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, intervalMs]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Poll /api/status so live capture counts stay fresh. */
export function useStatus(intervalMs = 5000): ApiState<Status> {
  return useApiData(() => api.status(), [], intervalMs);
}