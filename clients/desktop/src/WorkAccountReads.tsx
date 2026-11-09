import { useEffect, useRef, useState } from "react";
import { accountId } from "./account-frame";
import { Client } from "./transport";

type Grant = {
  id: string;
  task_revision: number;
  label: string;
  origin: string;
  read_path: string;
};

type Page = { text: string; truncated: boolean };

export function WorkAccountReads({
  client,
  task,
  revision,
}: {
  client: Client;
  task: string;
  revision: number;
}) {
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    setGrants(null);
    setPage(null);
    setError("");
    setBusy(false);
    return () => {
      request.current?.abort();
      request.current = null;
    };
  }, [client, task, revision]);

  async function load(grant?: Grant) {
    if (request.current) return;
    const pending = new AbortController();
    request.current = pending;
    setBusy(true);
    setPage(null);
    setError("");
    const path = `/v1/work/tasks/${task}/account-grants`;
    try {
      if (grant) {
        const response = await client.request<Page>(
          path + "/" + grant.id + "/read",
          "POST",
          undefined,
          pending.signal,
        );
        if (request.current === pending) setPage(response);
      } else {
        const result = await client.request<Grant[]>(
          path,
          "GET",
          undefined,
          pending.signal,
        );
        if (request.current === pending)
          setGrants(
            result.filter(
              (g) => g.task_revision === revision && accountId.test(g.id),
            ),
          );
      }
    } catch {
      if (request.current === pending) {
        if (!grant) setGrants(null);
        setError(
          "Account access is unavailable. Refresh permissions or ask the owner to review the grant.",
        );
      }
    } finally {
      if (request.current === pending) {
        request.current = null;
        setBusy(false);
      }
    }
  }

  function clear() {
    request.current?.abort();
    request.current = null;
    setGrants(null);
    setPage(null);
    setError("");
    setBusy(false);
  }

  return (
    <section aria-label="Private account reads">
      <button type="button" disabled={busy} onClick={() => void load()}>
        {grants
          ? "Refresh private account grants"
          : "Check private account grants"}
      </button>
      {(grants || busy || error) && (
        <button type="button" onClick={clear}>
          Close private account view
        </button>
      )}
      {busy && <p role="status">Checking private account access…</p>}
      {error && <p role="alert">{error}</p>}
      {grants?.length === 0 && (
        <p>No current account grants for this task and device.</p>
      )}
      {grants?.map((grant) => (
        <p key={grant.id}>
          {grant.label} — {grant.origin}
          {grant.read_path}{" "}
          <button
            type="button"
            disabled={busy}
            onClick={() => void load(grant)}
          >
            Read approved page
          </button>
        </p>
      ))}
      {page && (
        <>
          <p>
            Private page text is shown here only. It is not attached to the task
            or sent to the model.
          </p>
          <pre aria-label="Private account page">{page.text}</pre>
          {page.truncated && <p>Only the beginning of the page is shown.</p>}
        </>
      )}
    </section>
  );
}
