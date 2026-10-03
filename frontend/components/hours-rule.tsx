"use client";

import { Checkbox, SuffixInput } from "@/components/ui";

// An optional rule measured in hours: the checkbox and its sentence on top, the hours below with the unit inside.
export function HoursRule({
  label,
  checkboxLabel,
  inputLabel,
  checked,
  onToggle,
  value,
  onValue,
  max,
}: {
  label: string;
  checkboxLabel: string;
  inputLabel: string;
  checked: boolean;
  onToggle: (checked: boolean) => void;
  value: string | number;
  onValue: (value: string) => void;
  max?: number;
}) {
  return (
    <div className="flex flex-col gap-2">
      <label className="flex cursor-pointer items-start gap-2.5 text-[13px] font-medium text-text2">
        <Checkbox aria-label={checkboxLabel} checked={checked} onChange={(e) => onToggle(e.target.checked)} />
        <span className="pt-0.5">{label}</span>
      </label>
      <SuffixInput
        aria-label={inputLabel}
        suffix="h"
        type="number"
        min={1}
        max={max}
        disabled={!checked}
        className="font-mono disabled:opacity-50"
        value={value}
        onChange={(e) => onValue(e.target.value)}
      />
    </div>
  );
}
