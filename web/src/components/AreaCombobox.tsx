import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { api, type AreaSuggestion } from "../lib/api";
import { TextInput } from "./ui";

type Props = {
  id: string;
  describedBy?: string;
  country: string;
  value: AreaSuggestion | null;
  onChange: (area: AreaSuggestion | null) => void;
};

/** Town / district autocomplete limited to one country (OpenStreetMap Photon via the API). */
export function AreaCombobox({ id, describedBy, country, value, onChange }: Props) {
  const listId = useId();
  const [text, setText] = useState(value?.label ?? "");
  const [options, setOptions] = useState<AreaSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState<"idle" | "loading" | "error" | "empty">("idle");
  const request = useRef(0);

  useEffect(() => setText(value?.label ?? ""), [value]);

  useEffect(() => {
    const q = text.trim();
    if (!country || q.length < 2 || q === value?.label) {
      setOptions([]);
      setStatus("idle");
      return;
    }
    const call = ++request.current;
    setStatus("loading");
    const timer = window.setTimeout(async () => {
      try {
        const found = await api<AreaSuggestion[]>(`/api/search/areas?country=${country}&q=${encodeURIComponent(q)}`);
        if (call !== request.current) return;
        setOptions(found);
        setActive(found.length ? 0 : -1);
        setStatus(found.length ? "idle" : "empty");
        setOpen(true);
      } catch {
        if (call === request.current) setStatus("error");
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [text, country, value]);

  function choose(area: AreaSuggestion) {
    onChange(area);
    setText(area.label);
    setOpen(false);
    setOptions([]);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" && options.length) {
      event.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % options.length);
    } else if (event.key === "ArrowUp" && options.length) {
      event.preventDefault();
      setActive((i) => (i <= 0 ? options.length - 1 : i - 1));
    } else if (event.key === "Enter" && open && active >= 0 && options[active]) {
      event.preventDefault();
      choose(options[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  const expanded = open && (options.length > 0 || status === "empty");
  return (
    <div className="combo">
      <TextInput
        id={id}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-activedescendant={expanded && active >= 0 ? `${listId}-${active}` : undefined}
        aria-describedby={describedBy}
        autoComplete="off"
        disabled={!country}
        placeholder={country ? "Start typing a town, district or region" : "Choose a country first"}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          if (value) onChange(null);
        }}
        onKeyDown={onKeyDown}
        onFocus={() => options.length && setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
      />
      {expanded && (
        <ul className="combo-list" role="listbox" id={listId}>
          {options.map((option, index) => (
            <li
              key={option.id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(option)}
              onMouseEnter={() => setActive(index)}
            >
              <span>{option.label}</span>
              <span className="muted">{option.kind === "region" ? "District / region" : "Town"}</span>
            </li>
          ))}
          {status === "empty" && (
            <li role="option" aria-disabled="true" aria-selected={false} className="muted">
              Nothing found in this country
            </li>
          )}
        </ul>
      )}
      {status === "error" && <span className="field-error">Place search is not available right now. Try again in a moment.</span>}
    </div>
  );
}
