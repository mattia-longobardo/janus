import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { ProvidersSection } from "./providers";

const LIST = {
  available: [
    { kind: "pihole", label: "Pi-hole", roles: ["dhcp", "dns"], capabilities: [], policies: ["full", "lan_only"], secret_fields: ["password"],
      schema: { properties: { url: { type: "string", title: "Url" }, password: { type: "string", title: "Password" } } }, description: "", docs_url: "" },
    { kind: "unifi", label: "UniFi", roles: ["dhcp"], capabilities: [], policies: ["full"], secret_fields: ["password"],
      schema: { properties: { url: { type: "string", title: "Url" } } }, description: "", docs_url: "" },
  ],
  roles: { dhcp: { kind: "pihole", label: "Pi-hole", source: "env", config: { url: "http://pi.hole", password: true } }, dns: null },
};

const options = (select: HTMLElement) => [...select.querySelectorAll("option")].map((o) => o.textContent);

it("offers only kinds that support the role and warns before switching DHCP", async () => {
  vi.spyOn(api, "get").mockResolvedValue(LIST);
  const put = vi.spyOn(api, "put").mockResolvedValue(LIST.roles.dhcp);
  render(<ProvidersSection />);
  const dns = await screen.findByLabelText("DNS provider");
  expect(options(dns)).toEqual(["Same as DHCP (Pi-hole)", "None", "Pi-hole"]);
  expect(screen.queryByText(/switches Janus back to dry-run/)).toBeNull();
  await userEvent.selectOptions(screen.getByLabelText("DHCP & access provider"), "unifi");
  expect(screen.getByText(/switches Janus back to dry-run/)).toBeTruthy();
  await userEvent.type(screen.getByLabelText("Url"), "https://unifi.example");
  await userEvent.click(screen.getByRole("button", { name: "Save DHCP & access" }));
  expect(put).toHaveBeenCalledWith("/providers/dhcp", { kind: "unifi", config: { url: "https://unifi.example" } });
});

it("lets DNS follow the DHCP provider without a second form", async () => {
  const shared = { ...LIST, roles: { ...LIST.roles, dns: { ...LIST.roles.dhcp, shared: true } } };
  vi.spyOn(api, "get").mockResolvedValue(shared);
  const put = vi.spyOn(api, "put").mockResolvedValue(null);
  render(<ProvidersSection />);
  const dns = (await screen.findByLabelText("DNS provider")) as HTMLSelectElement;
  expect(dns.value).toBe("same");
  expect(screen.getAllByLabelText("Url")).toHaveLength(1);
  await userEvent.selectOptions(dns, "none");
  await userEvent.click(screen.getByRole("button", { name: "Save DNS" }));
  expect(put).toHaveBeenCalledWith("/providers/dns", { kind: null });
  await userEvent.selectOptions(dns, "same");
  expect(screen.getAllByLabelText("Url")).toHaveLength(1);
});

it("tests the saved connection and shows the answer", async () => {
  vi.spyOn(api, "get").mockResolvedValue(LIST);
  const post = vi.spyOn(api, "post").mockResolvedValue({ ok: false, detail: "Pi-hole refused the password" });
  render(<ProvidersSection />);
  await userEvent.click((await screen.findAllByRole("button", { name: "Test connection" }))[0]);
  expect(post).toHaveBeenCalledWith("/providers/dhcp/test");
  expect(await screen.findByText("Pi-hole refused the password")).toBeTruthy();
});
