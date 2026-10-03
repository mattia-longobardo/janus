import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { GenericConfigForm } from "@/providers/generic-config-form";
import type { ConfigFormProps } from "@/providers/types";

function Stateful({ onChange, value, ...props }: ConfigFormProps) {
  const [current, setCurrent] = useState(value);
  return <GenericConfigForm {...props} value={current} onChange={(patch) => { setCurrent((v) => ({ ...v, ...patch })); onChange(patch); }} />;
}

it("renders fields from the JSON schema and hides secret values", async () => {
  const onChange = vi.fn();
  render(<GenericConfigForm onChange={onChange} secretFields={["password"]}
    value={{ url: "http://pi.hole", password: true, lease: "24h", verify_tls: false }}
    schema={{ properties: { url: { type: "string", title: "Url" }, password: { type: "string", title: "Password" },
                            lease: { type: "string", title: "Lease" }, verify_tls: { type: "boolean", title: "Verify Tls" } } }} />);
  expect((screen.getByLabelText("Url") as HTMLInputElement).value).toBe("http://pi.hole");
  expect(screen.queryByDisplayValue("true")).toBeNull();
  expect(screen.getByText("•••• set")).toBeTruthy();
  await userEvent.click(screen.getByLabelText("Verify Tls"));
  expect(onChange).toHaveBeenLastCalledWith({ verify_tls: true });
});

it("maps numbers, short enums and long enums to their own controls", async () => {
  const onChange = vi.fn();
  render(<Stateful onChange={onChange} secretFields={[]} value={{ port: 443 }}
    schema={{ properties: {
      port: { type: "integer", title: "Port", description: "HTTPS port" },
      mode: { type: "string", title: "Mode", enum: ["a", "b"], default: "a" },
      site: { type: "string", title: "Site", enum: ["s1", "s2", "s3", "s4", "s5"], default: "s1" },
    } }} />);
  expect(screen.getByText("HTTPS port")).toBeTruthy();
  const port = screen.getByLabelText("Port") as HTMLInputElement;
  expect(port.type).toBe("number");
  await userEvent.clear(port);
  expect(onChange).toHaveBeenLastCalledWith({ port: null });
  await userEvent.type(port, "8443");
  expect(onChange).toHaveBeenLastCalledWith({ port: 8443 });
  await userEvent.click(screen.getByRole("button", { name: "b" }));
  expect(onChange).toHaveBeenLastCalledWith({ mode: "b" });
  await userEvent.selectOptions(screen.getByLabelText("Site"), "s4");
  expect(onChange).toHaveBeenLastCalledWith({ site: "s4" });
});
