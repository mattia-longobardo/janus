import { describe, expect, it } from "vitest";

import { CutoverPage } from "@/providers/pihole/cutover-page";

import ProviderPage from "./page";

const open = (kind: string, slug?: string[]) => ProviderPage({ params: Promise.resolve({ kind, slug }) });

describe("provider pages", () => {
  it("opens the named page, or the first one without a slug", async () => {
    expect((await open("pihole", ["cutover"])).type).toBe(CutoverPage);
    expect((await open("pihole")).type).toBe(CutoverPage);
  });

  it("is a 404 for unknown providers and slugs", async () => {
    await expect(open("pihole", ["nope"])).rejects.toThrow();
    await expect(open("acme")).rejects.toThrow();
    await expect(open("pihole", ["cutover", "extra"])).rejects.toThrow();
  });
});
