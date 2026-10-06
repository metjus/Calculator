import type { ReactNode } from "react";

export type Slice = { label: string; value: number; color: string };

const R = 40;
const C = 2 * Math.PI * R;

/** Ring chart with the number in the middle; every slice also has a title for hover and screen readers. */
export function Donut({ slices, size = "lg", center, label }: { slices: Slice[]; size?: "lg" | "sm"; center: ReactNode; label: string }) {
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const visible = slices.filter((s) => s.value > 0);
  const gap = visible.length > 1 ? 1.8 : 0;
  let offset = 0;
  return (
    <div className={`donut donut-${size}`}>
      <svg viewBox="0 0 100 100" role="img" aria-label={`${label}: ${slices.map((s) => `${s.label} ${s.value}`).join(", ")}`}>
        <g transform="rotate(-90 50 50)">
          <circle cx="50" cy="50" r={R} className="donut-track" />
          {total > 0 &&
            visible.map((s) => {
              const length = (s.value / total) * C;
              const dash = Math.max(length - gap, 0.5);
              const circle = (
                <circle key={s.label} cx="50" cy="50" r={R} style={{ stroke: s.color, strokeDasharray: `${dash} ${C - dash}`, strokeDashoffset: -offset }}>
                  <title>{`${s.label}: ${s.value}`}</title>
                </circle>
              );
              offset += length;
              return circle;
            })}
        </g>
      </svg>
      <div className="donut-center">{center}</div>
    </div>
  );
}

export function Legend({ slices, percent }: { slices: Slice[]; percent?: boolean }) {
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  return (
    <ul className="legend">
      {slices.map((s) => (
        <li key={s.label}>
          <span className="legend-dot" style={{ background: s.color }} aria-hidden />
          <span className="legend-label">{s.label}</span>
          <span className="legend-n num">{s.value}</span>
          {percent && <span className="legend-p num">{total ? `${Math.round((s.value / total) * 100)} %` : "—"}</span>}
        </li>
      ))}
    </ul>
  );
}

export type Bar = { key: string; label: string; value: number };

/** Horizontal bars; with `onPick` each bar is a toggle button (used to filter the websites table). */
export function Bars({ bars, max, selected, onPick }: { bars: Bar[]; max: number; selected?: string | null; onPick?: (key: string) => void }) {
  return (
    <div className="bars">
      {bars.map((b) => {
        const inner = (
          <>
            <span className="bar-top">
              <span className="bar-label">{b.label}</span>
              <span className="bar-value num">{b.value}</span>
            </span>
            <span className="bar-track">
              <span className="bar-fill" style={{ width: `${max ? (b.value / max) * 100 : 0}%` }} />
            </span>
          </>
        );
        return onPick ? (
          <button key={b.key} type="button" className={`bar${selected === b.key ? " selected" : ""}`} aria-pressed={selected === b.key} onClick={() => onPick(b.key)}>
            {inner}
          </button>
        ) : (
          <div key={b.key} className="bar">
            {inner}
          </div>
        );
      })}
    </div>
  );
}
