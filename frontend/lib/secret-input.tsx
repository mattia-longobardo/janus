"use client";

import { useState } from "react";

import { Button, Field, inputClass } from "@/components/ui";

// onChange(undefined) = leave unchanged, "" = clear the stored value, anything else = new value.
export function SecretInput({ label, isSet, onChange }: { label: string; isSet: boolean; onChange: (value: string | undefined) => void }) {
  const [mode, setMode] = useState<"view" | "edit" | "clear">("view");

  function pick(next: "view" | "edit" | "clear") {
    setMode(next);
    onChange(next === "clear" ? "" : undefined);
  }

  if (mode === "edit") {
    return (
      <Field label={label}>
        <div className="flex gap-2">
          <input
            type="password"
            autoComplete="new-password"
            autoFocus
            className={`${inputClass} font-mono`}
            onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}
          />
          <Button onClick={() => pick("view")}>Cancel</Button>
        </div>
      </Field>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[13px] font-medium text-text2">{label}</span>
      <div className="flex items-center gap-2">
        <span className="flex h-11 flex-1 items-center rounded-lg border border-line2 bg-bg px-3 font-mono text-[15px] text-muted">
          {mode === "clear" ? "will be cleared" : isSet ? "•••• set" : "not set"}
        </span>
        {mode === "clear" ? (
          <Button onClick={() => pick("view")}>Undo</Button>
        ) : (
          <>
            <Button aria-label={`Change ${label}`} onClick={() => pick("edit")}>
              Change
            </Button>
            {isSet && (
              <Button variant="danger" aria-label={`Clear ${label}`} onClick={() => pick("clear")}>
                Clear
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
