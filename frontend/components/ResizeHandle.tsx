"use client";

/**
 * Draggable divider between workspace panels (V2-UX-001).
 *
 * Pointer Events rather than mouse events, so a trackpad, touch screen and mouse all work
 * through one path. `setPointerCapture` keeps the drag alive when the cursor outruns the
 * 5px-wide handle — without it, a fast drag detaches and the panel stops following.
 *
 * Keyboard accessible: the handle is a `separator` with arrow-key nudging, because a
 * drag-only control is unusable without a pointing device.
 */

import { useCallback, useRef } from "react";

interface Props {
  orientation: "vertical" | "horizontal";
  /** Current size of the panel being resized, in px. */
  value: number;
  /** Called with the new size during the drag. */
  onChange: (next: number) => void;
  /** Called once when the drag ends, for persistence. */
  onCommit?: (next: number) => void;
  min: number;
  max: number;
  label: string;
  /** Vertical: dragging right grows the panel. Horizontal: dragging up grows it. */
  invert?: boolean;
}

const KEYBOARD_STEP = 16;

export function ResizeHandle({
  orientation,
  value,
  onChange,
  onCommit,
  min,
  max,
  label,
  invert = false,
}: Props) {
  const vertical = orientation === "vertical";
  const start = useRef({ pointer: 0, size: 0 });
  const latest = useRef(value);
  latest.current = value;

  const clamp = useCallback(
    (n: number) => Math.round(Math.min(max, Math.max(min, n))),
    [min, max],
  );

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const element = event.currentTarget;
      element.setPointerCapture(event.pointerId);
      start.current = {
        pointer: vertical ? event.clientX : event.clientY,
        size: latest.current,
      };
      element.dataset.dragging = "true";
    },
    [vertical],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.currentTarget.dataset.dragging !== "true") return;
      const current = vertical ? event.clientX : event.clientY;
      const delta = current - start.current.pointer;
      const next = clamp(start.current.size + (invert ? -delta : delta));
      if (next !== latest.current) onChange(next);
    },
    [vertical, invert, clamp, onChange],
  );

  const endDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const element = event.currentTarget;
      if (element.dataset.dragging !== "true") return;
      delete element.dataset.dragging;
      if (element.hasPointerCapture(event.pointerId)) {
        element.releasePointerCapture(event.pointerId);
      }
      onCommit?.(latest.current);
    },
    [onCommit],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const grow = vertical ? "ArrowRight" : "ArrowUp";
      const shrink = vertical ? "ArrowLeft" : "ArrowDown";
      let next: number | null = null;
      if (event.key === grow) next = clamp(latest.current + KEYBOARD_STEP);
      else if (event.key === shrink) next = clamp(latest.current - KEYBOARD_STEP);
      else if (event.key === "Home") next = min;
      else if (event.key === "End") next = max;
      if (next === null) return;
      event.preventDefault();
      onChange(next);
      onCommit?.(next);
    },
    [vertical, clamp, min, max, onChange, onCommit],
  );

  return (
    <div
      className={`resize-handle ${vertical ? "vertical" : "horizontal"}`}
      role="separator"
      tabIndex={0}
      aria-orientation={vertical ? "vertical" : "horizontal"}
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      title={`${label} — drag, or use arrow keys`}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onLostPointerCapture={endDrag}
      onKeyDown={handleKeyDown}
      onDoubleClick={() => {
        // Double-click to snap back is a convention users expect from split panes.
        onChange(min);
        onCommit?.(min);
      }}
    >
      <span className="grip" aria-hidden />
    </div>
  );
}
