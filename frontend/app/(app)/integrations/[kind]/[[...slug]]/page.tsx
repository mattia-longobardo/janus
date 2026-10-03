import { notFound } from "next/navigation";

import { PROVIDER_UI } from "@/providers/registry";

// Pages a provider plugin brings along: /integrations/<kind> opens its first page, /integrations/<kind>/<slug> a given one.
export default async function ProviderPage({ params }: { params: Promise<{ kind: string; slug?: string[] }> }) {
  const { kind, slug } = await params;
  const pages = PROVIDER_UI[kind]?.pages ?? [];
  if (slug && slug.length > 1) notFound();
  const page = slug ? pages.find((p) => p.slug === slug[0]) : pages[0];
  if (!page) notFound();
  const { Component } = page;
  return <Component />;
}
