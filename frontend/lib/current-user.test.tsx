import { render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { EnforcementSwitch } from "@/app/(app)/settings/sections/enforcement";
import { CurrentUserProvider, useCurrentUser } from "@/lib/current-user";

const ADMIN = { id: "a", name: "admin", role: "admin", source: "local" };

function Probe() {
  const user = useCurrentUser();
  return <span>{user ? `${user.name}:${user.role}` : "nobody"}</span>;
}

describe("CurrentUserProvider", () => {
  it("hands the server-read user to components, and null outside the provider", () => {
    render(
      <CurrentUserProvider user={ADMIN}>
        <Probe />
      </CurrentUserProvider>,
    );
    expect(screen.getByText("admin:admin")).toBeTruthy();
    render(<Probe />);
    expect(screen.getByText("nobody")).toBeTruthy();
  });

  it("lets admin-only settings render on the server without a session hook", () => {
    const html = renderToString(
      <CurrentUserProvider user={ADMIN}>
        <EnforcementSwitch mode="dry-run" hasDhcp onChanged={vi.fn()} />
      </CurrentUserProvider>,
    );
    expect(html).toContain("Switch to apply");
  });
});
