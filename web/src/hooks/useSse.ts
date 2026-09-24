import { useEffect, useRef, useState } from "react";

export interface UseSseOptions<T> {
  url: string;
  /** SSE event name to listen for (e.g. "loot", "status"). */
  event: string;
  onEvent: (data: T) => void;
  enabled?: boolean;
}

export interface SseState {
  connected: boolean;
  error: string | null;
}

/** Subscribe to a Server-Sent Events stream and invoke onEvent per frame. */
export function useSse<T>({ url, event, onEvent, enabled = true }: UseSseOptions<T>): SseState {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") {
      setConnected(false);
      return;
    }
    const source = new EventSource(url);
    source.onopen = () => {
      setConnected(true);
      setError(null);
    };
    source.onerror = () => {
      setConnected(false);
    };
    const handler = (e: MessageEvent<string>) => {
      try {
        onEventRef.current(JSON.parse(e.data) as T);
      } catch {
        setError("Failed to parse streamed payload");
      }
    };
    source.addEventListener(event, handler);
    return () => {
      source.removeEventListener(event, handler);
      source.close();
    };
  }, [url, event, enabled]);

  return { connected, error };
}