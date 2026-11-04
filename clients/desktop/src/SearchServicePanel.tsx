import { useEffect, useRef, useState } from "react";
import { Client } from "./transport";

interface Service {
  job: {
    id: string;
    action: string;
    status: string;
    error_code: string | null;
  } | null;
}
export function SearchServicePanel({
  client,
  active,
}: {
  client: Client;
  active: boolean;
}) {
  const [service, setService] = useState<Service | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ id: string; action: "start" | "stop" } | null>(null);
  useEffect(() => {
    if (!active) return;
    let live = true;
    async function refresh() {
      try {
        const value = await client.request<Service>("/v1/search/service");
        if (!live) return;
        setService(value);
        if (
          value.job?.id === pending.current?.id &&
          value.job?.status !== "running"
        )
          pending.current = null;
      } catch (e) {
        if (live) setError(String(e));
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 3000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [client, active]);
  async function manage(action: "start" | "stop") {
    if (pending.current && pending.current.action !== action) return;
    pending.current ??= { id: crypto.randomUUID(), action };
    setBusy(true);
    setError("");
    try {
      await client.request(
        `/v1/search/service/${action}/${pending.current.id}`,
        "POST",
      );
      setService(await client.request<Service>("/v1/search/service"));
    } catch (e) {
      setError(`${String(e)} Retry reuses the same request.`);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Managed search service">
      <h2>Install local search</h2>
      <p>
        Docker Desktop with Linux containers must be running. Setup downloads
        the pinned SearXNG image, starts a service available only on your PC,
        and saves its address. Public searches contact external search engines.
        No chats, files or credentials are mounted in this service.
      </p>
      {error && <p role="alert">{error}</p>}
      <button
        disabled={
          busy ||
          service?.job?.status === "running" ||
          pending.current?.action === "stop"
        }
        onClick={() => void manage("start")}
      >
        Install / start search service
      </button>
      <button
        disabled={
          busy ||
          service?.job?.status === "running" ||
          pending.current?.action === "start"
        }
        onClick={() => void manage("stop")}
      >
        Stop managed search service
      </button>
      {service?.job && (
        <p>
          Last operation: {service.job.action} — {service.job.status}{" "}
          {service.job.error_code}
        </p>
      )}
      <p>
        Setup can take several minutes. You can leave this page and return to
        check the result.
      </p>
    </section>
  );
}
