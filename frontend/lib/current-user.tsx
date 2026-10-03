"use client";

import { createContext, useContext, type ReactNode } from "react";

// The signed-in user, read on the server by the (app) layout and handed down. Components use this instead of
// authClient.useSession(): better-auth/react resolves its own React copy during SSR (it is a server external
// package), so calling its hooks while rendering on the server throws.
export type CurrentUser = {
  id: string;
  name: string;
  role: string | null;
  source: string | null;
};

const CurrentUserContext = createContext<CurrentUser | null>(null);

export function CurrentUserProvider({ user, children }: { user: CurrentUser; children: ReactNode }) {
  return <CurrentUserContext.Provider value={user}>{children}</CurrentUserContext.Provider>;
}

export function useCurrentUser(): CurrentUser | null {
  return useContext(CurrentUserContext);
}
