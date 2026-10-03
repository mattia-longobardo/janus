"use client";

import { Menu } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Logo, Sidebar } from "@/components/sidebar";
import { type CurrentUser, CurrentUserProvider } from "@/lib/current-user";
import { FeaturesProvider } from "@/lib/features";
import { SettingsProvider } from "@/lib/settings-context";

export function Shell({
  children,
  user,
}: {
  children: ReactNode;
  user: CurrentUser;
}) {
  const [open, setOpen] = useState(false);
  return (
    <CurrentUserProvider user={user}>
      <SettingsProvider>
        <FeaturesProvider>
          <div className="min-h-dvh lg:flex">
            <Sidebar open={open} onClose={() => setOpen(false)} user={user.name} />
            <div className="min-w-0 flex-1">
              <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-side px-4 lg:hidden">
                <Logo />
                <button
                  type="button"
                  aria-label="Open menu"
                  onClick={() => setOpen(true)}
                  className="flex size-11 items-center justify-center rounded-lg border border-line2"
                >
                  <Menu className="size-5" />
                </button>
              </header>
              <main className="mx-auto max-w-[1500px] px-4 py-6 lg:px-10 lg:py-9">
                {children}
              </main>
            </div>
          </div>
        </FeaturesProvider>
      </SettingsProvider>
    </CurrentUserProvider>
  );
}
