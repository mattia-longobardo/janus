import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RulesTable, priorityLabel } from "@/app/(app)/notifications/rules-table";

describe("RulesTable", () => {
  it("toggles one channel of one event", async () => {
    const onChange = vi.fn();
    render(
      <RulesTable
        rules={[
          { event_type: "device.new", label: "New device waiting for approval", email: true, gotify: true, priority: 8, default_priority: 8 },
          { event_type: "device.offline", label: "Known device offline", email: false, gotify: true, priority: 5, default_priority: 5 },
        ]}
        onChange={onChange}
        channels={["email", "gotify"]}
      />,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Known device offline email" }));
    expect(onChange).toHaveBeenCalledWith({ event_type: "device.offline", label: "Known device offline", email: true, gotify: true, priority: 5, default_priority: 5 });
  });
});

describe("RulesTable hints", () => {
  it("explains when an event is muted", () => {
    render(
      <RulesTable rules={[{ event_type: "device.offline", label: "Known device offline", email: false, gotify: true, priority: 5, default_priority: 5 }]} onChange={vi.fn()} channels={["email", "gotify"]} />,
    );
    expect(screen.getByText("Muted during maintenance windows")).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: "Known device offline Gotify" }) as HTMLInputElement).checked).toBe(true);
  });
});


describe("RulesTable priority", () => {
  const rule = { event_type: "device.offline", label: "Known device offline", email: false, gotify: true, priority: 5, default_priority: 5 };

  it("changes the Gotify priority of one event", async () => {
    const onChange = vi.fn();
    render(<RulesTable rules={[rule]} onChange={onChange} channels={["email", "gotify"]} />);
    const select = screen.getByRole("combobox", { name: "Known device offline Gotify priority" }) as HTMLSelectElement;
    expect(select.value).toBe("5");
    expect(screen.getByRole("option", { name: "5 · normal (default)" })).toBeTruthy();
    await userEvent.selectOptions(select, "9");
    expect(onChange).toHaveBeenCalledWith({ ...rule, priority: 9 });
  });

  it("marks custom priorities and disables the select when Gotify is off", () => {
    const { rerender } = render(<RulesTable rules={[{ ...rule, priority: 9 }]} onChange={vi.fn()} channels={["email", "gotify"]} />);
    expect(screen.getByText("custom · default 5")).toBeTruthy();
    rerender(<RulesTable rules={[{ ...rule, gotify: false }]} onChange={vi.fn()} channels={["email", "gotify"]} />);
    expect((screen.getByRole("combobox", { name: "Known device offline Gotify priority" }) as HTMLSelectElement).disabled).toBe(true);
  });

  it("names the Gotify priority bands", () => {
    expect([0, 2, 4, 8, 10].map(priorityLabel)).toEqual(["0 · silent", "2 · low", "4 · normal", "8 · high", "10 · max"]);
  });
});

describe("RulesTable channels", () => {
  const rule = { event_type: "device.offline", label: "Known device offline", email: false, gotify: true, priority: 5, default_priority: 5 };

  it("renders only the columns of ready channels", () => {
    render(<RulesTable rules={[rule]} onChange={vi.fn()} channels={["gotify"]} />);
    expect(screen.queryByText("Email")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Known device offline email" })).toBeNull();
    expect(screen.getByText("Gotify")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Known device offline Gotify" })).toBeTruthy();
  });

  it("drops the priority column when Gotify is not ready", () => {
    render(<RulesTable rules={[rule]} onChange={vi.fn()} channels={["email"]} />);
    expect(screen.queryByText("Priority")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
