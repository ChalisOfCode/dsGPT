import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Client, native } from "./transport";
import { Icon } from "./Icon";

type Progress = {
  status: "idle" | "running" | "succeeded" | "paired" | "needs_attention";
  phase: string;
  message: string;
};
const idle: Progress = {
  status: "idle",
  phase: "",
  message:
    "Your existing wireless debugging connection handles setup. Keep your Pixel unlocked, with both devices on the same home Wi-Fi and connected to Tailscale.",
};

export function PhoneConnection({
  client,
  request,
}: {
  client: Client;
  request: number;
}) {
  const [progress, setProgress] = useState<Progress>(idle);
  const [error, setError] = useState("");
  const [phone, setPhone] = useState<{
    paired: boolean;
    online: boolean;
  } | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const starting = useRef(false),
    generation = useRef(0);
  const available = native && client.origin === "http://127.0.0.1:18765";
  useEffect(() => {
    if (!available) return;
    let live = true,
      first = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const current = generation.current;
      try {
        const value = await invoke<Progress>("phone_setup_status");
        const connection = await client.request<{
          paired: boolean;
          online: boolean;
        }>("/v1/devices/phone-status");
        if (live) setPhone(connection);
        if (live && current === generation.current) {
          setProgress(value);
          if (first && value.status === "running") dialog.current?.showModal();
          first = false;
        }
      } catch {
        /* A start failure is shown directly; a transient status read is retried. */
      }
      if (live) timer = setTimeout(poll, 1500);
    }
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [available, client]);
  async function start() {
    dialog.current?.showModal();
    if (starting.current || progress.status === "running") return;
    setError("");
    if (!available) {
      setError(
        "Open the installed dsGPT app on the PC that runs your models to connect your Pixel automatically.",
      );
      return;
    }
    starting.current = true;
    generation.current++;
    setProgress({
      status: "running",
      phase: "desktop",
      message: "Starting automatic Pixel connection…",
    });
    try {
      setProgress(await invoke<Progress>("start_phone_setup"));
    } catch (e) {
      setProgress(idle);
      setError(String(e));
    } finally {
      starting.current = false;
    }
  }
  useEffect(() => {
    if (request > 0) void start();
  }, [request]);
  return (
    <>
      <button
        className="phone-trigger"
        ref={trigger}
        title="Connect Pixel automatically"
        aria-label="Connect Pixel automatically"
        onClick={() => {
          if (phone?.paired || progress.status === "succeeded")
            dialog.current?.showModal();
          else void start();
        }}
      >
        <Icon name="phone" />
        <span>
          {progress.status === "running"
            ? "Connecting Pixel…"
            : phone?.online
              ? "Pixel connected"
              : phone?.paired
                ? "Pixel paired"
                : "Connect Pixel"}
        </span>
        <i
          className={`phone-dot ${phone?.online ? "succeeded" : phone?.paired ? "paired" : progress.status}`}
        />
      </button>
      <dialog
        ref={dialog}
        className="phone-dialog"
        aria-labelledby="phone-heading"
        onClose={() => trigger.current?.focus()}
      >
        <div className="phone-dialog-title">
          <Icon name="phone" />
          <h2 id="phone-heading">Connect your Pixel</h2>
          <button
            className="icon-button"
            aria-label="Close phone connection"
            onClick={() => dialog.current?.close()}
          >
            <Icon name="close" />
          </button>
        </div>
        <p>
          dsGPT sets up the private address, updates the phone app and connects
          it for you.
        </p>
        <ol className="phone-steps">
          <li>Prepare your private Tailscale connection</li>
          <li>Update dsGPT Mobile over wireless debugging</li>
          <li>Verify and save the phone connection</li>
        </ol>
        <div
          className={`phone-progress ${progress.status}`}
          role="status"
          aria-live="polite"
        >
          {progress.status === "running" && (
            <span className="phone-spinner" aria-hidden="true" />
          )}
          <span>
            {phone?.online && progress.status !== "running"
              ? "Your Pixel is connected and authenticated over Tailscale. Wireless debugging is only used for app updates."
              : phone?.paired && progress.status !== "running"
                ? "Your Pixel pairing is saved. Open dsGPT Mobile to connect over Tailscale. You do not need to pair again after an update."
                : progress.message}
          </span>
        </div>
        {error && <p role="alert">{error}</p>}
        <p className="phone-hint">
          Once connected, use dsGPT Mobile anywhere Tailscale connects. Keep
          your PC awake with dsGPT running.
        </p>
        <div className="phone-actions">
          <button
            disabled={progress.status === "running"}
            onClick={() => void start()}
          >
            {progress.status === "succeeded"
              ? "Check connection again"
              : progress.status === "needs_attention" || error
                ? "Retry automatic connection"
                : "Connect automatically"}
          </button>
          <button onClick={() => dialog.current?.close()}>
            {progress.status === "running" ? "Continue in background" : "Done"}
          </button>
        </div>
      </dialog>
    </>
  );
}
