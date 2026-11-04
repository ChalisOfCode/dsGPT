import { useEffect, useRef, useState } from "react";
import { Client } from "./transport";
import { Icon } from "./Icon";

export function pcm16(input: Float32Array, rate: number): string {
  const count = Math.floor((input.length * 16000) / rate);
  const bytes = new Uint8Array(count * 2),
    view = new DataView(bytes.buffer);
  for (let i = 0; i < count; i++) {
    const sample = Math.max(
      -1,
      Math.min(1, input[Math.floor((i * rate) / 16000)]),
    );
    view.setInt16(
      i * 2,
      Math.round(sample * (sample < 0 ? 32768 : 32767)),
      true,
    );
  }
  return btoa(String.fromCharCode(...bytes));
}

export function DictationButton({
  client,
  value,
  onChange,
  disabled = false,
  onError,
  active = true,
  onListening,
}: {
  client: Client;
  value: string;
  onChange: (text: string) => void;
  disabled?: boolean;
  onError: (message: string) => void;
  active?: boolean;
  onListening?: (listening: boolean) => void;
}) {
  const [listening, setListening] = useState(false),
    [starting, setStarting] = useState(false);
  const session = useRef<{
    id: string;
    stream: MediaStream;
    audio: AudioContext;
    node: ScriptProcessorNode;
    sequence: number;
    queue: Promise<void>;
    pending: number;
    base: string;
    last: string;
    stopped: boolean;
  } | null>(null);
  const props = useRef({ value, onChange, onError, onListening });
  props.current = { value, onChange, onError, onListening };
  const epoch = useRef(0);
  function display(s: NonNullable<typeof session.current>, text: string) {
    if (session.current !== s) return;
    s.last = [s.base.trimEnd(), text].filter(Boolean).join(" ");
    props.current.onChange(s.last);
  }
  async function stop(flush = true) {
    epoch.current++;
    const s = session.current;
    if (!s) return;
    if (s.stopped) {
      if (!flush) session.current = null;
      return;
    }
    s.stopped = true;
    s.stream.getTracks().forEach((t) => t.stop());
    s.node.disconnect();
    void s.audio.close();
    setListening(false);
    props.current.onListening?.(false);
    if (!flush) session.current = null;
    try {
      await s.queue;
      if (flush) {
        const result = await client.request<{ text: string }>(
          `/v1/dictation/${s.id}`,
          "POST",
          { sequence: s.sequence++, audio: "", final: true },
        );
        display(s, result.text);
      } else await client.request(`/v1/dictation/${s.id}`, "DELETE");
    } catch (error) {
      if (flush) props.current.onError(String(error));
    } finally {
      if (session.current === s) session.current = null;
    }
  }
  useEffect(
    () => () => {
      void stop(false);
    },
    [client],
  );
  useEffect(() => {
    if (!active || disabled) void stop(false);
  }, [active, disabled]);
  useEffect(() => {
    const s = session.current;
    // Editing, switching chats or sending a draft must never be overwritten by a late hypothesis.
    if (s && value !== s.last && value !== s.base) void stop(false);
  }, [value]);
  async function start() {
    if (starting || session.current) return;
    const own = ++epoch.current;
    setStarting(true);
    let stream: MediaStream | undefined,
      audio: AudioContext | undefined,
      id: string | undefined;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      const result = await client.request<{ id: string }>(
        "/v1/dictation",
        "POST",
      );
      id = result.id;
      if (own !== epoch.current) {
        await client.request(`/v1/dictation/${id}`, "DELETE");
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      audio = new AudioContext({ sampleRate: 16000 });
      await audio.resume();
      const node = audio.createScriptProcessor(4096, 1, 1);
      const s = {
        id,
        stream,
        audio,
        node,
        sequence: 0,
        queue: Promise.resolve(),
        pending: 0,
        base: props.current.value,
        last: props.current.value,
        stopped: false,
      };
      session.current = s;
      node.onaudioprocess = (event) => {
        if (s.stopped) return;
        if (++s.pending > 12) {
          props.current.onError(
            "The PC cannot keep up with live audio. Recording stopped; your visible text is preserved.",
          );
          void stop(false);
          return;
        }
        const chunk = pcm16(
          event.inputBuffer.getChannelData(0),
          s.audio.sampleRate,
        );
        s.queue = s.queue
          .then(async () => {
            if (session.current !== s) return;
            const result = await client.request<{ text: string }>(
              `/v1/dictation/${s.id}`,
              "POST",
              { sequence: s.sequence++, audio: chunk },
            );
            display(s, result.text);
          })
          .catch((error) => {
            props.current.onError(String(error));
            void stop(false);
          })
          .finally(() => {
            s.pending--;
          });
      };
      audio.createMediaStreamSource(stream).connect(node);
      node.connect(audio.destination);
      setListening(true);
      props.current.onListening?.(true);
    } catch (error) {
      stream?.getTracks().forEach((t) => t.stop());
      void audio?.close();
      if (id)
        void client.request(`/v1/dictation/${id}`, "DELETE").catch(() => {});
      props.current.onError(
        `Dictation could not start. Allow microphone access in Windows and dsGPT. ${String(error)}`,
      );
    } finally {
      setStarting(false);
    }
  }
  return (
    <button
      type="button"
      className={`icon-button dictate-button${listening ? " recording" : ""}`}
      aria-label={listening ? "Stop dictation" : "Live dictation"}
      aria-pressed={listening}
      title={
        listening
          ? "Listening locally — words appear as you speak. Tap to finish, then edit."
          : "Dictate live · English · processed on your PC"
      }
      disabled={disabled || starting}
      onClick={() => {
        if (listening) void stop();
        else void start();
      }}
    >
      <Icon name={listening ? "stop" : "mic"} />
      {starting && <span className="sr-only">Starting microphone</span>}
    </button>
  );
}
