import { useEffect, useRef, useState } from "react";
import { SearchServicePanel } from "./SearchServicePanel";
import { Client, openSource } from "./transport";

interface SearchSettings {
  origin: string | null;
  revision: number;
  configured: boolean;
  configuration_owned: boolean;
  can_configure: boolean;
  test_query: string;
  check_in_progress: boolean;
  last_check: {
    checked_at: string;
    status: string;
    result_count: number;
    engine_failures: number;
    error_code: string | null;
  } | null;
}
const checkLabels: Record<string, string> = {
  passed: "Test returned results",
  partial: "Some search engines did not respond",
  empty: "Test returned no results",
  failed: "Test failed",
};

export function SearchPanel({
  client,
  active,
}: {
  client: Client;
  active: boolean;
}) {
  const [settings, setSettings] = useState<SearchSettings | null>(null);
  const [origin, setOrigin] = useState("http://127.0.0.1:8888");
  const [busy, setBusy] = useState(false),
    [online, setOnline] = useState(false);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0),
    [dirty, setDirty] = useState(false);
  const [disabling, setDisabling] = useState<SearchSettings | null>(null);
  const dirtyRef = useRef(false),
    editRevision = useRef<number | null>(null);
  const mutating = useRef(false);
  function accept(value: SearchSettings) {
    setSettings(value);
    if (!dirtyRef.current) {
      setOrigin(value.origin || "http://127.0.0.1:8888");
      editRevision.current = value.revision;
    }
  }
  useEffect(() => {
    if (!active || busy) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await client.request<SearchSettings>(
          "/v1/research/settings",
          "GET",
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          accept(value);
          setOnline(true);
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setOnline(false);
          setError(
            `${String(e)} Search settings require backend 0.3.0.dev10 or newer and Chat or owner access.`,
          );
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 5000);
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [client, active, busy, refresh]);

  async function mutate(kind: "save" | "disable" | "check") {
    if (!settings?.can_configure || !online || mutating.current) return;
    mutating.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const value = await client.request<SearchSettings>(
        kind === "check" ? "/v1/research/check" : "/v1/research/settings",
        kind === "check" ? "POST" : "PUT",
        kind === "check"
          ? { revision: settings.revision }
          : {
              origin: kind === "disable" ? null : origin.trim(),
              revision:
                kind === "disable"
                  ? disabling?.revision
                  : (editRevision.current ?? settings.revision),
            },
      );
      if (kind !== "check") {
        dirtyRef.current = false;
        setDirty(false);
      }
      accept(value);
      setNotice(
        kind === "check"
          ? "Test result saved."
          : kind === "disable"
            ? "Web search disabled. The separate search service and saved sources are preserved."
            : "Search address saved. Run a test when you want to check it.",
      );
    } catch (e) {
      setError(
        `${String(e)} Review the refreshed address and last test before retrying. No request is replayed automatically.`,
      );
    } finally {
      mutating.current = false;
      setBusy(false);
      setDisabling(null);
      setRefresh((n) => n + 1);
    }
  }
  return (
    <section hidden={!active} aria-label="Web search settings">
      <h1>Web search</h1>
      <p>
        Setup manages the local search service automatically. Web Auto plans
        searches from your current prompt, reads public pages and shows sources.
        Private files, chat history and memories are not sent to search engines.
        Your local model writes the answer; sites can be unavailable and sources
        can be wrong.
      </p>
      <p>
        Install local search below or connect an existing SearXNG service with
        JSON results enabled. Saving an address does not send a query.
      </p>
      <button
        onClick={() =>
          void openSource(
            "https://docs.searxng.org/admin/installation.html",
          ).catch((e) => setError(String(e)))
        }
      >
        SearXNG setup documentation
      </button>
      <button disabled={busy} onClick={() => setRefresh((n) => n + 1)}>
        Refresh search status
      </button>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {settings ? (
        <>
          {!online && (
            <p>Connection unavailable. This is the last known configuration.</p>
          )}
          <p aria-label="Current search address">
            {settings.configured
              ? `Configured address: ${settings.origin}`
              : "Web search is not configured."}
          </p>
          {!settings.can_configure && (
            <p>
              The desktop owner manages search configuration and runs connection
              tests.
            </p>
          )}
          {settings.configuration_owned && (
            <p>
              This address comes from backend.toml and is read-only here.
              App-saved settings are preserved and become active if that file
              setting is removed.
            </p>
          )}
          {settings.can_configure && !settings.configuration_owned && (
            <details>
              <summary>Advanced search address</summary>
              <form
                className="model-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void mutate("save");
                }}
              >
                <label>
                  Local search address
                  <input
                    value={origin}
                    disabled={busy || !online}
                    maxLength={2048}
                    onChange={(e) => {
                      dirtyRef.current = true;
                      setDirty(true);
                      setOrigin(e.target.value);
                    }}
                  />
                </label>
                <p>
                  Use http://127.0.0.1:PORT or http://[::1]:PORT. The service is
                  on the PC, including when your phone uses it.
                </p>
                {dirty && editRevision.current !== settings.revision && (
                  <p>
                    The saved settings changed while you were editing. Review
                    them before saving.
                  </p>
                )}
                <div className="work-actions">
                  <button disabled={busy || !online || !origin.trim()}>
                    Save search address
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      dirtyRef.current = false;
                      setDirty(false);
                      setError("");
                      accept(settings);
                      setRefresh((n) => n + 1);
                    }}
                  >
                    Clear update and reload
                  </button>
                  {settings.configured && (
                    <button
                      type="button"
                      disabled={busy || !online}
                      onClick={() => setDisabling(settings)}
                    >
                      Disable web search…
                    </button>
                  )}
                </div>
              </form>
            </details>
          )}
          {settings.can_configure && !settings.configuration_owned && (
            <SearchServicePanel client={client} active={active} />
          )}
          <h2>Last test</h2>
          <p>
            A test sends “{settings.test_query}” through your configured service
            to public search engines. It sends no chat history or saved memory.
            A past result does not guarantee current availability or factual
            accuracy.
          </p>
          {settings.can_configure && (
            <button
              disabled={
                busy ||
                !online ||
                !settings.configured ||
                settings.check_in_progress
              }
              onClick={() => void mutate("check")}
            >
              Run test search
            </button>
          )}
          {settings.check_in_progress && (
            <p>A search test is in progress on the PC.</p>
          )}
          {settings.last_check ? (
            <div aria-label="Last search test">
              <p>
                {checkLabels[settings.last_check.status] ||
                  "Unknown test result"}
              </p>
              <p>Checked: {settings.last_check.checked_at}</p>
              <p>
                {settings.last_check.result_count} public results ·{" "}
                {settings.last_check.engine_failures} engine failures
              </p>
              {settings.last_check.error_code && (
                <p>
                  {settings.last_check.error_code}. Check that the service is
                  running and JSON output is enabled.
                </p>
              )}
            </div>
          ) : (
            <p>No test is recorded for this address and revision.</p>
          )}
          <p>
            Research remains opt-in for each message. Explicit public source
            URLs work without web search.
          </p>
        </>
      ) : (
        <p>Loading search settings…</p>
      )}
      {disabling && (
        <div
          role="dialog"
          aria-label="Disable web search"
          className="model-confirm"
        >
          <h2>Disable web search?</h2>
          <p>
            This removes the configured address {disabling.origin}. The separate
            service and saved sources remain. Accepted web research must finish
            or be cancelled first.
          </p>
          <button disabled={busy} onClick={() => void mutate("disable")}>
            Confirm disable
          </button>
          <button disabled={busy} onClick={() => setDisabling(null)}>
            Keep web search
          </button>
        </div>
      )}
    </section>
  );
}
