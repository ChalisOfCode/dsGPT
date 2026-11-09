import { useEffect, useRef, useState } from "react";
import { Client } from "./transport";

type Session = { id: string; label: string; origin: string; read_path: string };
type Task = {
  id: string;
  title: string;
  revision: number;
  requirements: string;
};
type Device = { id: string; name: string; scopes: string[]; revoked: number };
type Grant = {
  id: string;
  task_id: string;
  task_revision: number;
  device_id: string;
  expires_at: number;
};

export function AccountPanel({ client }: { client: Client }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [session, setSession] = useState("");
  const [task, setTask] = useState("");
  const [device, setDevice] = useState("");
  const [ready, setReady] = useState(false);
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [reviewed, setReviewed] = useState(false);
  const lock = useRef(false);
  const epoch = useRef(0);
  const selected = sessions.find((s) => s.id === session);
  const chosen = tasks.find((t) => t.id === task);
  useEffect(() => {
    const own = ++epoch.current;
    let cancelled = false;
    setReady(false);
    setReviewed(false);
    setGrants([]);
    setError("");
    void (async () => {
      try {
        const result = await client.request<{
          available: boolean;
          sessions: Session[];
        }>("/v1/account-sessions");
        const [ts, ds, gs] = await Promise.all([
          session
            ? client.request<Task[]>("/v1/work/tasks?limit=20")
            : Promise.resolve([]),
          client.request<Device[]>("/v1/devices?limit=200"),
          session && result.sessions.some((s) => s.id === session)
            ? client.request<Grant[]>(`/v1/account-sessions/${session}/grants`)
            : Promise.resolve([]),
        ]);
        if (cancelled || own !== epoch.current) return;
        setSessions(result.sessions);
        setAvailable(result.available);
        setTasks(ts);
        setDevices(ds.filter((d) => !d.revoked && d.scopes.includes("work")));
        setGrants(gs);
        setReady(true);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
      epoch.current++;
    };
  }, [client, session, refresh]);
  async function mutate(path: string, method: string, body?: unknown) {
    if (lock.current || !ready) return;
    lock.current = true;
    setBusy(true);
    setReady(false);
    setReviewed(false);
    setError("");
    try {
      await client.request(path, method, body);
      setNotice("Account permissions updated.");
    } catch {
      setNotice(
        "The response was interrupted or rejected. Review the refreshed permissions before trying again; no automatic retry was sent.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
      setRefresh((n) => n + 1);
    }
  }
  return (
    <section aria-label="Account permissions">
      <h2>Account permissions</h2>
      <p>
        Manage access from the local desktop owner connection. Browser sign-in
        is not available in this build; no passwords or cookies should be pasted
        here.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <button disabled={busy} onClick={() => setRefresh((n) => n + 1)}>
        Refresh account permissions
      </button>
      {ready && !available && (
        <p>Protected account storage requires Windows.</p>
      )}
      {ready && sessions.length === 0 && <p>No account sessions connected.</p>}
      <fieldset disabled={busy || !ready}>
        <label>
          Account session
          <select
            aria-label="Account session"
            value={session}
            onChange={(e) => {
              setSession(e.target.value);
              setReviewed(false);
              setNotice("");
            }}
          >
            <option value="">Choose an account</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label} — {s.origin}
              </option>
            ))}
          </select>
        </label>
        {selected && (
          <>
            <p>
              Approved page: {selected.origin}
              {selected.read_path}
            </p>
            <p>
              Revocation prevents future reads and discards pending responses.
              It cannot undo requests already sent or sign you out of the
              website.
            </p>
            <button
              onClick={() =>
                void mutate(`/v1/account-sessions/${session}`, "DELETE")
              }
            >
              Revoke account session
            </button>
            <h3>Grant page access</h3>
            <label>
              Task
              <select
                aria-label="Account access task"
                value={task}
                onChange={(e) => {
                  setTask(e.target.value);
                  setReviewed(false);
                }}
              >
                <option value="">Choose a task</option>
                {tasks.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title} — revision {t.revision}
                  </option>
                ))}
              </select>
            </label>
            {chosen && (
              <details>
                <summary>Review task requirements</summary>
                <pre>{chosen.requirements}</pre>
              </details>
            )}
            <label>
              Device
              <select
                aria-label="Account access device"
                value={device}
                onChange={(e) => {
                  setDevice(e.target.value);
                  setReviewed(false);
                }}
              >
                <option value="">Choose a device</option>
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} — {d.id}
                  </option>
                ))}
              </select>
            </label>
            <p>
              Shows up to 20 recent tasks and 200 devices. Access lasts 15
              minutes, applies only to this task revision and page, and permits
              no website writes. Changing the task invalidates access.
            </p>
            <label>
              <input
                type="checkbox"
                checked={reviewed}
                onChange={(e) => setReviewed(e.target.checked)}
              />
              I approve this device reading this account page for the selected
              task.
            </label>
            <button
              disabled={
                !available ||
                !chosen ||
                !devices.some((d) => d.id === device) ||
                !reviewed
              }
              onClick={() =>
                void mutate(`/v1/account-sessions/${session}/grants`, "POST", {
                  task_id: task,
                  task_revision: chosen!.revision,
                  device_id: device,
                  lifetime_seconds: 900,
                })
              }
            >
              Grant 15-minute read access
            </button>
            <h3>Existing grants</h3>
            {grants.length === 0 && <p>No grants for this account.</p>}
            {grants.map((g) => (
              <article key={g.id} aria-label={`Account grant ${g.id}`}>
                <p>
                  Task{" "}
                  {tasks.find((t) => t.id === g.task_id)?.title || g.task_id},
                  revision {g.task_revision}; device{" "}
                  {devices.find((d) => d.id === g.device_id)?.name ||
                    g.device_id}
                  . Expires {new Date(g.expires_at * 1000).toLocaleString()}.
                  Authorization is rechecked on every read.
                </p>
                <button
                  onClick={() =>
                    void mutate(
                      `/v1/account-sessions/${session}/grants/${g.id}`,
                      "DELETE",
                    )
                  }
                >
                  Revoke read grant
                </button>
              </article>
            ))}
          </>
        )}
      </fieldset>
    </section>
  );
}
