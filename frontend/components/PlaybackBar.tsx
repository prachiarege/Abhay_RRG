"use client";

/**
 * Historical playback (SRS 21).
 *
 * The scrubber selects a date and the backend recomputes using only data available up to
 * it, so what you see is what was knowable then. Every offered date is past the warm-up
 * window, so no position on the track produces an empty chart.
 */

import { useEffect, useRef, useState } from "react";

import { fmtDate } from "@/lib/format";

interface Props {
  dates: string[];
  /** null means "latest", which is the last date on the track. */
  asOf: string | null;
  loading: boolean;
  onChange: (date: string | null) => void;
}

const PLAY_INTERVAL_MS = 550;

export function PlaybackBar({ dates, asOf, loading, onChange }: Props) {
  const [playing, setPlaying] = useState(false);
  const timerRef = useRef<number | null>(null);

  const lastIndex = dates.length - 1;
  const currentIndex = asOf === null ? lastIndex : dates.indexOf(asOf);
  const index = currentIndex >= 0 ? currentIndex : lastIndex;

  const seek = (next: number) => {
    if (dates.length === 0) return;
    const clamped = Math.max(0, Math.min(lastIndex, next));
    // Selecting the final date sends null rather than that date, so the view returns to
    // genuine "latest" and keeps tracking new data as it arrives.
    onChange(clamped === lastIndex ? null : dates[clamped]);
  };

  // Animation. Stops itself at the end rather than looping, which would make it unclear
  // whether you are looking at history or the present.
  useEffect(() => {
    if (!playing || dates.length === 0) return;

    timerRef.current = window.setInterval(() => {
      const position = asOf === null ? lastIndex : dates.indexOf(asOf);
      if (position < 0 || position >= lastIndex) {
        setPlaying(false);
        return;
      }
      seek(position + 1);
    }, PLAY_INTERVAL_MS);

    return () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
      timerRef.current = null;
    };
    // `seek` is stable enough for this interval; re-created each tick by design so the
    // closure always reads the current date.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, asOf, dates, lastIndex]);

  const atStart = index <= 0;
  const atEnd = index >= lastIndex;
  const disabled = dates.length === 0;

  return (
    <div className="playback">
      <div className="playback-controls">
        <button
          type="button"
          className="icon-btn"
          onClick={() => seek(0)}
          disabled={disabled || atStart}
          title="Jump to earliest available date"
          aria-label="Jump to earliest"
        >
          |◀
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={() => seek(index - 1)}
          disabled={disabled || atStart}
          title="Step back one period"
          aria-label="Step back"
        >
          ◀
        </button>
        <button
          type="button"
          className={`icon-btn${playing ? " active" : ""}`}
          onClick={() => setPlaying((p) => !p)}
          disabled={disabled || atEnd}
          title={playing ? "Pause" : "Play forward through history"}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? "❙❙" : "▶"}
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={() => seek(index + 1)}
          disabled={disabled || atEnd}
          title="Step forward one period"
          aria-label="Step forward"
        >
          ▶
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={() => {
            setPlaying(false);
            onChange(null);
          }}
          disabled={disabled || atEnd}
          title="Return to the latest date"
          aria-label="Jump to latest"
        >
          ▶|
        </button>
      </div>

      <div className="scrubber">
        <span className="playback-note">{dates[0] ? fmtDate(dates[0]) : "–"}</span>
        <input
          type="range"
          min={0}
          max={Math.max(0, lastIndex)}
          value={index}
          disabled={disabled}
          onChange={(e) => {
            setPlaying(false);
            seek(Number(e.target.value));
          }}
          aria-label="Historical date"
        />
        <span className="playback-note">{dates[lastIndex] ? fmtDate(dates[lastIndex]) : "–"}</span>
      </div>

      <div className="playback-date">
        {loading ? (
          <span style={{ color: "var(--text-dim)" }}>loading…</span>
        ) : (
          <>
            <b>{dates[index] ? fmtDate(dates[index]) : "–"}</b>
            {asOf === null && (
              <span style={{ color: "var(--pos)", marginLeft: 6, fontSize: 10 }}>LIVE</span>
            )}
          </>
        )}
      </div>
    </div>
  );
}
