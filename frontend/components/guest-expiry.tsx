"use client";

import { useState } from "react";

import { Segmented, inputClass } from "@/components/ui";
import { PRESETS, describeRules, todayIn } from "@/lib/guests";
import { useSettings } from "@/lib/settings-context";
import type { ExpiryInput, Guest, GuestRules } from "@/lib/types";

type Mode = "" | `${number}` | "date" | "none";

// Clearing a guest's own expiry hands it back to the global rules, so "Never" only exists while both rules are off;
// otherwise the same choice reads "Use default (…)". Nothing is emitted until the user picks something, and a guest
// that already has its own expiry starts with no option selected (the parent keeps it unchanged).
export function GuestExpiry({
  value,
  rules,
  onChange,
}: {
  value?: Pick<Guest, "guest_expires_at">;
  rules?: GuestRules;
  onChange: (input: ExpiryInput) => void;
}) {
  const { settings } = useSettings();
  const fallback = describeRules(rules);
  const [mode, setMode] = useState<Mode>(value?.guest_expires_at ? "" : "none");
  const [date, setDate] = useState("");

  function pick(next: Mode) {
    setMode(next);
    if (next === "none") onChange({ clear_expiry: true });
    else if (next === "date") onChange(date ? { expires_on: date } : {});
    else if (next) onChange({ expires_in_hours: Number(next) });
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div className="max-w-full overflow-x-auto">
        <Segmented<Mode>
          label="Expiry"
          value={mode}
          onChange={pick}
          options={[
            ...PRESETS.map((p) => ({ value: `${p.hours}` as Mode, label: p.label })),
            { value: "date", label: "Pick a date" },
            { value: "none", label: fallback ? `Use default (${fallback})` : "Never" },
          ]}
        />
      </div>
      {mode === "date" && (
        <input
          type="date"
          aria-label="Expiry date"
          className={`${inputClass} w-auto font-mono`}
          min={todayIn(settings.timezone)}
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
            onChange(e.target.value ? { expires_on: e.target.value } : {});
          }}
        />
      )}
    </div>
  );
}
