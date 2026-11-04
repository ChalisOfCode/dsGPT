import { useEffect, useRef, useState } from "react";
import { Client } from "./transport";

interface Device {
  id: string;
  name: string;
  role: string;
  scopes: string[];
  created_at: string;
  revoked?: number;
}
const scopeNames: Record<string, string> = {
  chat: "Chat and personal memory",
  work: "Work and project memory",
  diagnostics: "Diagnostics",
  models: "Model management",
  admin: "Device administration and model management",
};
function permissions(device: Device) {
  return device.scopes
    .filter((s) => s !== "models" || !device.scopes.includes("admin"))
    .map((s) => scopeNames[s] || s)
    .join(" · ");
}

export function DevicesPanel({
  client,
  active,
  onConnectPhone,
}: {
  client: Client;
  active: boolean;
  onConnectPhone: () => void;
}) {
  const [self, setSelf] = useState<Device | null>(null),
    [devices, setDevices] = useState<Device[]>([]),
    [offset, setOffset] = useState(0),
    [refresh, setRefresh] = useState(0),
    [online, setOnline] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [revoking, setRevoking] = useState<Device | null>(null),
    [pairModels, setPairModels] = useState(false),
    [pair, setPair] = useState<{
      code: string;
      expires_at_unix: number;
    } | null>(null),
    [now, setNow] = useState(Date.now());
  const mutating = useRef(false),
    epoch = useRef(0);
  const owner = self?.scopes.includes("admin") === true;
  useEffect(() => {
    if (!active || busy) return;
    const abort = new AbortController(),
      own = ++epoch.current;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const current = await client.request<Device>(
          "/v1/device",
          "GET",
          undefined,
          abort.signal,
        );
        const rows = current.scopes.includes("admin")
          ? await client.request<Device[]>(
              `/v1/devices?limit=50&offset=${offset}`,
              "GET",
              undefined,
              abort.signal,
            )
          : [];
        if (abort.signal.aborted || own !== epoch.current) return;
        setSelf(current);
        setDevices(rows);
        setOnline(true);
      } catch (e) {
        if (!abort.signal.aborted && own === epoch.current) {
          setOnline(false);
          setError(
            `${String(e)} Device controls require backend 0.3.0.dev8 or newer. Check the connection and backend version.`,
          );
        }
      }
      if (!abort.signal.aborted) timer = setTimeout(poll, 4000);
    }
    void poll();
    return () => {
      abort.abort();
      clearTimeout(timer);
      epoch.current++;
    };
  }, [client, active, offset, refresh, busy]);
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  async function generate() {
    if (mutating.current || !owner || !online) return;
    mutating.current = true;
    setBusy(true);
    setPair(null);
    setNotice("");
    setError("");
    try {
      const code = await client.request<{
        code: string;
        expires_at_unix: number;
      }>("/v1/pairings", "POST", {
        scopes: [
          "chat",
          "work",
          "diagnostics",
          ...(pairModels ? ["models"] : []),
        ],
      });
      setPair(code);
      setNow(Date.now());
    } catch (e) {
      setError(
        `${String(e)} No code is available here. Generate another only when you want a new code.`,
      );
    } finally {
      mutating.current = false;
      setBusy(false);
    }
  }
  async function revoke() {
    if (!revoking || mutating.current || !owner || !online) return;
    const target = revoking;
    mutating.current = true;
    setBusy(true);
    setNotice("");
    setError("");
    try {
      await client.request(`/v1/devices/${target.id}`, "DELETE");
      setNotice(
        `Access revoked for ${target.name}. Accepted replies, Work and downloads may continue on your PC.`,
      );
    } catch (e) {
      setError(
        `${String(e)} Inspect the refreshed device status before retrying.`,
      );
    } finally {
      setRevoking(null);
      mutating.current = false;
      setBusy(false);
      setRefresh((v) => v + 1);
    }
  }
  return (
    <section
      className="devices-panel"
      aria-label="Connected devices workspace"
      hidden={!active}
    >
      <h1>Connected Devices</h1>
      <p>
        Pairing again creates a new credential. Revoke the old device entry
        separately when you no longer want it to connect.
      </p>
      <button
        disabled={busy}
        onClick={() => {
          setError("");
          setRefresh((v) => v + 1);
        }}
      >
        Refresh devices
      </button>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {busy && <p role="status">Applying device change…</p>}
      {self && (
        <article className="model-card" aria-label="This connection">
          <h2>This connection</h2>
          <p>
            {self.name} · {self.role}
          </p>
          <p className="source-url">Device ID: {self.id}</p>
          <p>{permissions(self)}</p>
          <p>
            {online
              ? "Connection verified"
              : "Last known identity; connection not verified"}
          </p>
        </article>
      )}
      {!self && !error && <p>Loading device identity…</p>}
      {self && !owner && (
        <p>
          This credential can view its own permissions. Device pairing and
          revocation require the desktop owner.
        </p>
      )}
      {owner && (
        <>
          <h2>Pair a phone</h2>
          <p>
            Connect your Pixel automatically using its existing wireless
            debugging connection. dsGPT prepares the private HTTPS address and
            saves the connection on your phone.
          </p>
          <button disabled={busy || !online} onClick={onConnectPhone}>
            Connect Pixel automatically
          </button>
          <details className="manual-pairing">
            <summary>Manual connection</summary>
            <p>
              Codes are one-use and expire after five minutes. Give the code
              only to the phone you intend to pair. Normal pairing allows Chat,
              Work and diagnostics.
            </p>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={pairModels}
                disabled={busy || !online}
                onChange={(e) => {
                  setPairModels(e.target.checked);
                  setPair(null);
                }}
              />
              Allow model management
            </label>
            <p>
              Also allows this phone to download, install, register and remove
              dsGPT-managed models and runtimes on your PC. Existing device
              permissions are unchanged.
            </p>
            <button disabled={busy || !online} onClick={() => void generate()}>
              Generate pairing code
            </button>
            {pair &&
              (pair.expires_at_unix * 1000 > now ? (
                <div>
                  <pre className="code">{pair.code}</pre>
                  <p>
                    Expires at{" "}
                    {new Date(pair.expires_at_unix * 1000).toLocaleTimeString()}
                    . Redeeming it consumes it even if it is still shown here.
                  </p>
                  <button onClick={() => setPair(null)}>Hide code</button>
                  <small>
                    Hiding or replacing a code does not revoke it; any unused
                    code expires after five minutes.
                  </small>
                </div>
              ) : (
                <p>Pairing code expired. Generate a new one to pair.</p>
              ))}
          </details>
          <h2>Device access</h2>
          <p>
            Revocation blocks new authenticated requests. It preserves
            conversations and accepted jobs. Already downloaded or displayed
            content cannot be recalled.
          </p>
          {devices.map((d) => (
            <article
              className="model-card"
              key={d.id}
              aria-label={`Device ${d.id}`}
            >
              <h3>
                {d.name}
                {d.id === self?.id ? " · This connection" : ""}
              </h3>
              <p>
                {d.role} · {d.revoked ? "Access revoked" : "Access active"}
              </p>
              <p className="source-url">{d.id}</p>
              <p>Paired: {d.created_at}</p>
              <p>{permissions(d)}</p>
              {d.role === "owner" ? (
                <p>
                  Owner identity cannot be revoked here. Local owner recovery is
                  a separate operation.
                </p>
              ) : (
                !d.revoked && (
                  <button
                    disabled={busy || !online}
                    onClick={() => {
                      setRevoking(d);
                      setError("");
                    }}
                  >
                    Revoke access…
                  </button>
                )
              )}
            </article>
          ))}
          {devices.length === 0 && <p>No device entries on this page.</p>}
          <div className="model-actions">
            <button
              disabled={busy || offset === 0}
              onClick={() => setOffset((v) => Math.max(0, v - 50))}
            >
              Previous devices
            </button>
            <span>Page {Math.floor(offset / 50) + 1}</span>
            <button
              disabled={busy || devices.length < 50}
              onClick={() => setOffset((v) => v + 50)}
            >
              More devices
            </button>
          </div>
          {revoking && (
            <div
              className="model-confirm"
              role="alertdialog"
              aria-label="Revoke device access"
            >
              <h2>Revoke access for {revoking.name}?</h2>
              <p className="source-url">{revoking.id}</p>
              <p>
                This credential will stop connecting. The device needs a new
                pairing code to regain access. Accepted jobs and saved content
                on your PC remain.
              </p>
              <button disabled={busy || !online} onClick={() => void revoke()}>
                Confirm revocation
              </button>
              <button disabled={busy} onClick={() => setRevoking(null)}>
                Keep access
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
