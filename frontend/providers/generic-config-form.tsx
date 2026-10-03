"use client";

import { Checkbox, Field, Segmented, inputClass } from "@/components/ui";
import { SecretInput } from "@/lib/secret-input";
import type { ConfigFormProps, JsonSchemaProperty } from "@/providers/types";

// `X | None` fields arrive as anyOf: the first non-null branch says what to draw.
function shape(prop: JsonSchemaProperty): { type?: string; enum?: string[] } {
  const branch = prop.anyOf?.find((b) => b.type !== "null");
  return { type: prop.type ?? branch?.type, enum: prop.enum ?? branch?.enum };
}

function Hint({ text }: { text?: string }) {
  return text ? <span className="text-xs text-faint">{text}</span> : null;
}

// A form drawn from the provider's config schema, so a new provider needs no UI code. Secrets come in as booleans
// (set or not); `onChange` receives only the field that changed. For a secret `undefined` leaves the saved value and
// "" clears it; an emptied number sends null, which puts the default back.
export function GenericConfigForm({ schema, secretFields, value, onChange }: ConfigFormProps) {
  return (
    <div className="grid gap-3.5 sm:grid-cols-2">
      {Object.entries(schema.properties).map(([name, prop]) => {
        const label = prop.title ?? name;
        const { type, enum: options } = shape(prop);
        const current = value[name] !== undefined ? value[name] : prop.default;   // null = back to the default
        const set = (next: unknown) => onChange({ [name]: next });

        if (secretFields.includes(name)) {
          return (
            <div key={name} className="flex flex-col gap-2">
              <SecretInput label={label} isSet={Boolean(value[name])} onChange={set} />
              <Hint text={prop.description} />
            </div>
          );
        }
        if (type === "boolean") {
          return (
            <div key={name} className="flex flex-col justify-end gap-1">
              <Checkbox label={label} checked={Boolean(current)} onChange={(e) => set(e.target.checked)} />
              <Hint text={prop.description} />
            </div>
          );
        }
        if (options && options.length <= 4) {
          return (
            <div key={name} className="flex flex-col gap-2">
              <span className="text-[13px] font-medium text-text2">{label}</span>
              <div>
                <Segmented label={label} value={String(current ?? "")} options={options.map((o) => ({ value: o, label: o }))} onChange={set} />
              </div>
              <Hint text={prop.description} />
            </div>
          );
        }
        if (options) {
          return (
            <Field key={name} label={label} hint={prop.description}>
              <select className={inputClass} value={String(current ?? "")} onChange={(e) => set(e.target.value)}>
                {options.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </Field>
          );
        }
        const numeric = type === "integer" || type === "number";
        return (
          <Field key={name} label={label} hint={prop.description}>
            <input
              type={numeric ? "number" : "text"}
              step={type === "integer" ? 1 : undefined}
              className={`${inputClass} font-mono`}
              spellCheck={false}
              value={current === undefined || current === null ? "" : String(current)}
              onChange={(e) => set(numeric ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value)}
            />
          </Field>
        );
      })}
    </div>
  );
}
