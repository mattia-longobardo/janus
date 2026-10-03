"use client";

import clsx from "clsx";

import { CustomColor } from "@/components/custom-color";
import { GROUP_ICONS } from "@/lib/group-icons";

export const PALETTE = ["#6FB7FF", "#B69CF0", "#E58FB8", "#5CC8A8", "#A6D86A", "#E0A84E", "#F0765C", "#9AA3A8"];

export function ColorPicker({ value, onChange }: { value: string; onChange: (color: string) => void }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 text-[13px] font-medium text-text2">Color</legend>
      <div className="flex flex-wrap gap-2">
        {PALETTE.map((color) => {
          const active = value.toUpperCase() === color;
          return (
            <button
              key={color}
              type="button"
              aria-label={`Color ${color}`}
              aria-pressed={active}
              onClick={() => onChange(color)}
              className={clsx("size-8 rounded-lg", active ? "border-[3px] border-text" : "border border-line2")}
              style={{ background: color }}
            />
          );
        })}
        <CustomColor value={value} palette={PALETTE} onChange={onChange} />
      </div>
    </fieldset>
  );
}

export function IconPicker({ value, onChange }: { value: string; onChange: (icon: string) => void }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 text-[13px] font-medium text-text2">Icon</legend>
      <div className="flex flex-wrap gap-2">
        {Object.entries(GROUP_ICONS).map(([key, Icon]) => (
          <button
            key={key}
            type="button"
            aria-label={`Icon ${key}`}
            aria-pressed={value === key}
            onClick={() => onChange(key)}
            className={clsx(
              "flex size-10 items-center justify-center rounded-lg border text-text2",
              value === key ? "border-accent bg-accent-soft" : "border-line2 bg-card hover:text-text",
            )}
          >
            <Icon className="size-[18px]" aria-hidden />
          </button>
        ))}
      </div>
    </fieldset>
  );
}
