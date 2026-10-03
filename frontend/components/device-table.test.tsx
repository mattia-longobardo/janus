import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DeviceTable, sortDevices } from "@/components/device-table";
import { makeDevice, makeGroup } from "@/lib/test-data";

describe("DeviceTable", () => {
  it("shows name, group, IP, MAC and links to the detail page", () => {
    render(
      <DeviceTable
        devices={[makeDevice({ id: "d1", name: "TV_SALA", group_id: 1, static_ip: "192.168.1.155", private_mac: true, online: false })]}
        groups={[makeGroup({ id: 1, name: "Streaming" })]}
      />,
    );
    const row = screen.getByRole("row", { name: /TV_SALA/ });
    expect(within(row).getByRole("link", { name: "TV_SALA" }).getAttribute("href")).toBe("/devices/d1");
    expect(within(row).getByText("Streaming")).toBeTruthy();
    // The desktop column and the phone line under the name both carry the IP and status.
    expect(within(row).getAllByText("192.168.1.155")).toHaveLength(2);
    expect(within(row).getByText("private MAC")).toBeTruthy();
    expect(within(row).getAllByText("Offline")).toHaveLength(2);
  });

  it("folds status and IP under the name on phones, beside the badges", () => {
    render(
      <DeviceTable
        devices={[
          makeDevice({ id: "d1", name: "GATEWAY", static_ip: null, last_ip: "192.168.1.1", private_mac: true, online: true }),
          makeDevice({ id: "d2", name: "TV", static_ip: "192.168.1.155", online: false }),
        ]}
        groups={[makeGroup()]}
        onDelete={() => {}}
      />,
    );
    const gateway = screen.getByRole("row", { name: /GATEWAY/ });
    const nameCell = within(gateway).getByRole("link", { name: "GATEWAY" }).closest("td") as HTMLElement;
    expect(within(nameCell).getByText("private MAC")).toBeTruthy();
    const meta = nameCell.querySelector("[data-mobile-meta]") as HTMLElement;
    expect(meta.className).toContain("sm:hidden");
    expect(meta.textContent).toBe("Online192.168.1.1");
    expect(within(nameCell).queryByRole("button")).toBeNull();
    // The other columns only appear from the sm breakpoint up.
    const cells = [...gateway.querySelectorAll("td")];
    expect(cells.filter((td) => !td.classList.contains("hidden"))).toHaveLength(2);
    const tv = screen.getByRole("row", { name: /TV/ }).querySelector("[data-mobile-meta]") as HTMLElement;
    expect(tv.textContent).toBe("Offline192.168.1.155");
    const headers = screen.getAllByRole("columnheader").filter((th) => !th.className.includes("hidden"));
    expect(headers.map((th) => th.textContent)).toEqual(["Name", "Actions"]);
  });

  it("pages through every device and remembers the page size", async () => {
    const devices = Array.from({ length: 30 }, (_, i) => makeDevice({ id: `d${i}`, name: `DEV_${String(i).padStart(2, "0")}` }));
    render(<DeviceTable devices={devices} groups={[makeGroup()]} />);
    expect(screen.getAllByRole("link")).toHaveLength(25);
    expect(screen.getByText("1–25 of 30")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getAllByRole("link").map((a) => a.textContent)).toEqual(["DEV_25", "DEV_26", "DEV_27", "DEV_28", "DEV_29"]);
    await userEvent.selectOptions(screen.getByLabelText("Rows per page"), "50");
    expect(screen.getAllByRole("link")).toHaveLength(30);
    expect(localStorage.getItem("janus.pageSize")).toBe("50");
  });

  it("offers a delete action per row only when a handler is given", async () => {
    const onDelete = vi.fn();
    const device = makeDevice({ id: "d1", name: "OLD_TV" });
    const { rerender } = render(<DeviceTable devices={[device]} groups={[makeGroup()]} />);
    expect(screen.queryByRole("button", { name: "Delete OLD_TV" })).toBeNull();
    rerender(<DeviceTable devices={[device]} groups={[makeGroup()]} onDelete={onDelete} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete OLD_TV" }));
    expect(onDelete).toHaveBeenCalledWith(device);
  });

  it("sorts by a column and flips direction on a second click", async () => {
    const devices = [
      makeDevice({ id: "a", name: "TV", static_ip: "192.168.1.150" }),
      makeDevice({ id: "b", name: "LAPTOP", static_ip: "192.168.1.9" }),
      makeDevice({ id: "c", name: "printer", static_ip: "192.168.1.20" }),
    ];
    render(<DeviceTable devices={devices} groups={[makeGroup()]} />);
    const names = () => screen.getAllByRole("link").map((a) => a.textContent);
    expect(names()).toEqual(["TV", "LAPTOP", "printer"]);
    await userEvent.click(screen.getByRole("button", { name: /^Name/ }));
    expect(names()).toEqual(["LAPTOP", "printer", "TV"]);
    expect(screen.getByRole("columnheader", { name: /Name/ }).getAttribute("aria-sort")).toBe("ascending");
    await userEvent.click(screen.getByRole("button", { name: /^Name/ }));
    expect(names()).toEqual(["TV", "printer", "LAPTOP"]);
    await userEvent.click(screen.getByRole("button", { name: /^Static IP/ }));
    expect(names()).toEqual(["LAPTOP", "printer", "TV"]);
  });

  it("puts online devices and known vendors first", () => {
    const groups = [makeGroup()];
    const devices = [
      makeDevice({ id: "off", online: false, last_seen: "2026-10-01T08:00:00Z", vendor: null }),
      makeDevice({ id: "on", online: true, vendor: "Acme" }),
    ];
    expect(sortDevices(devices, groups, "status", "asc").map((d) => d.id)).toEqual(["on", "off"]);
    expect(sortDevices(devices, groups, "seen", "asc").map((d) => d.id)).toEqual(["on", "off"]);
    expect(sortDevices(devices, groups, "vendor", "asc").map((d) => d.id)).toEqual(["on", "off"]);
  });

  it("says when nothing matches", () => {
    render(<DeviceTable devices={[]} groups={[]} />);
    expect(screen.getByText("No devices match.")).toBeTruthy();
  });
});
