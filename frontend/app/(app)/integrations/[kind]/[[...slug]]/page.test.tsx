import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import { CutoverPage } from "@/providers/pihole/cutover-page";
import { ProviderPageGate } from "@/providers/provider-page-gate";

import ProviderPage from "./page";

type Gate = ReactElement<{ href: string; children: ReactElement }>;
const open = async (kind: string, slug?: string[]) => (await ProviderPage({ params: Promise.resolve({ kind, slug }) })) as Gate;
const NOT_FOUND = { digest: "NEXT_HTTP_ERROR_FALLBACK;404" };

describe("provider pages", () => {
  it("opens the named page, or the first one without a slug, behind the role gate", async () => {
    for (const page of [await open("pihole", ["cutover"]), await open("pihole")]) {
      expect(page.type).toBe(ProviderPageGate);
      expect(page.props.href).toBe("/integrations/pihole/cutover");
      expect(page.props.children.type).toBe(CutoverPage);
    }
  });

  it("is a 404 for unknown providers and slugs", async () => {
    await expect(open("pihole", ["nope"])).rejects.toMatchObject(NOT_FOUND);
    await expect(open("acme")).rejects.toMatchObject(NOT_FOUND);
    await expect(open("pihole", ["cutover", "extra"])).rejects.toMatchObject(NOT_FOUND);
  });
});
