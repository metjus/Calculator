import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

/** Load JSON from the API; `reload()` refetches. Errors are exposed, not thrown. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const latest = useRef(0);

  const reload = useCallback(async () => {
    if (!path) return;
    const call = ++latest.current;
    setLoading(true);
    try {
      const result = await api<T>(path);
      if (call === latest.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (call === latest.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      if (call === latest.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, setData, error, loading, reload };
}
