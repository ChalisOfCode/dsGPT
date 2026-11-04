import { useEffect, useState } from "react";
import { Client } from "./transport";

export function ThinkingPicker({
  client,
  model,
  value,
  onChange,
  disabled = false,
}: {
  client: Client;
  model: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const [choices, setChoices] = useState([
    { id: "auto", label: "Model default" },
  ]);
  const [help, setHelp] = useState("Loading supported thinking controls…");
  useEffect(() => {
    let live = true;
    setChoices([{ id: "auto", label: "Model default" }]);
    if (!model) return;
    client
      .request<{
        choices: { id: string; label: string }[];
        output_tokens: number;
      }>(`/v1/models/${encodeURIComponent(model)}/thinking`)
      .then((result) => {
        if (!live) return;
        if (!Array.isArray(result.choices)) throw Error("Unavailable controls");
        setChoices(result.choices);
        setHelp(
          `Controls reported by this local model. Thinking and answer share its ${result.output_tokens.toLocaleString()} token output limit.`,
        );
        if (!result.choices.some((c) => c.id === value)) onChange("auto");
      })
      .catch(() => {
        if (live) {
          setHelp(
            "Thinking controls unavailable. Start Ollama, then reselect the model.",
          );
          onChange("auto");
        }
      });
    return () => {
      live = false;
    };
  }, [client, model]);
  return (
    <select
      aria-label="Thinking effort"
      title={help}
      value={choices.some((c) => c.id === value) ? value : "auto"}
      disabled={disabled || choices.length < 2}
      onChange={(e) => onChange(e.target.value)}
    >
      {choices.map((choice) => (
        <option key={choice.id} value={choice.id}>
          {choice.label}
        </option>
      ))}
    </select>
  );
}

export function WebPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <select
      aria-label="Web search mode"
      title="Auto lets your local model search when needed. Public queries use this prompt only; files, history and memories stay out of search. Attachments turn automatic search off."
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="auto">Web · Auto</option>
      <option value="on">Web · On</option>
      <option value="off">Web · Off</option>
    </select>
  );
}
