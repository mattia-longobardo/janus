"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge, Button, Checkbox, Field, Notice, SCROLL_TARGET, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { authClient } from "@/lib/auth/client";
import { canRemoveOrDemote } from "@/lib/auth/last-admin";
import { SecretInput } from "@/lib/secret-input";
import type { AuthSettings } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const MIN_PASSWORD = 12;

type Account = { id: string; name: string; role?: string | null; source?: string | null };
type Message = { tone: "success" | "error"; text: string };
type ProviderDraft = {
  source?: string;
  key: number;
  id: string;
  name: string;
  discovery_url: string;
  client_id: string;
  client_secret: boolean;
  secret?: string;
  scopes: string;
  enabled: boolean;
};

function Heading({ children }: { children: string }) {
  return <h3 className="text-[15px] font-semibold">{children}</h3>;
}

function Result({ message }: { message?: Message }) {
  return message ? <Notice tone={message.tone}>{message.text}</Notice> : null;
}

function UsersPart({ selfId }: { selfId: string }) {
  const [users, setUsers] = useState<Account[]>([]);
  const [message, setMessage] = useState<Message>();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("user");
  const [resetFor, setResetFor] = useState<string>();
  const [resetPassword, setResetPassword] = useState("");

  const load = useCallback(async () => {
    const res = await authClient.admin.listUsers({ query: { limit: 200 } });
    if (res.error) setMessage({ tone: "error", text: res.error.message ?? "Could not load users" });
    else setUsers((res.data?.users ?? []) as Account[]);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<{ error?: { message?: string } | null }>, done: string) {
    const res = await action();
    if (res.error) setMessage({ tone: "error", text: res.error.message ?? "Failed" });
    else {
      setMessage({ tone: "success", text: done });
      await load();
    }
    return !res.error;
  }

  async function add() {
    const name = username.trim();
    if (password.length < MIN_PASSWORD) return setMessage({ tone: "error", text: `Password must be at least ${MIN_PASSWORD} characters` });
    const ok = await run(
      () => authClient.admin.createUser({ email: `${name}@local.invalid`, password, name, role: role as "user", data: { username: name, source: "local" } }),
      `User ${name} added`,
    );
    if (ok) {
      setUsername("");
      setPassword("");
    }
  }

  async function reset(user: Account) {
    if (resetPassword.length < MIN_PASSWORD) return setMessage({ tone: "error", text: `Password must be at least ${MIN_PASSWORD} characters` });
    const ok = await run(() => authClient.admin.setUserPassword({ userId: user.id, newPassword: resetPassword }), `Password reset for ${user.name}`);
    if (ok) {
      setResetFor(undefined);
      setResetPassword("");
    }
  }

  return (
    <div className="flex flex-col gap-3.5">
      <Heading>Users</Heading>
      <Result message={message} />
      <div className="flex flex-col divide-y divide-line">
        {users.map((u) => {
          const protectedAdmin = !canRemoveOrDemote(u, users);
          const isAdmin = u.role === "admin";
          return (
            <div key={u.id} className="flex flex-col gap-2 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-medium">{u.name}</span>
                <Badge>{u.source === "oidc" ? "OIDC" : "Local"}</Badge>
                <Badge tone={isAdmin ? "accent" : "neutral"}>{isAdmin ? "admin" : "user"}</Badge>
                <Button
                  aria-label={`Reset password for ${u.name}`}
                  disabled={u.source === "oidc"}
                  onClick={() => {
                    setResetFor(resetFor === u.id ? undefined : u.id);
                    setResetPassword("");
                  }}
                >
                  Reset password
                </Button>
                <Button
                  aria-label={isAdmin ? `Make ${u.name} user` : `Make ${u.name} admin`}
                  disabled={isAdmin && protectedAdmin}
                  onClick={() => {
                    if (!window.confirm(isAdmin ? `Make ${u.name} a plain user?` : `Make ${u.name} an admin?`)) return;
                    void run(() => authClient.admin.setRole({ userId: u.id, role: isAdmin ? "user" : "admin" }), `Role updated for ${u.name}`);
                  }}
                >
                  {isAdmin ? "Make user" : "Make admin"}
                </Button>
                <Button
                  variant="danger"
                  aria-label={`Delete ${u.name}`}
                  disabled={protectedAdmin || u.id === selfId}
                  onClick={() => {
                    if (!window.confirm(`Delete ${u.name}? This cannot be undone.`)) return;
                    void run(() => authClient.admin.removeUser({ userId: u.id }), `User ${u.name} deleted`);
                  }}
                >
                  Delete
                </Button>
              </div>
              {resetFor === u.id && (
                <div className="flex gap-2">
                  <input
                    type="password"
                    autoComplete="new-password"
                    aria-label={`New password for ${u.name}`}
                    className={inputClass}
                    value={resetPassword}
                    onChange={(e) => setResetPassword(e.target.value)}
                  />
                  <Button variant="primary" onClick={() => void reset(u)}>
                    Set password
                  </Button>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="grid items-start gap-3.5 sm:grid-cols-2">
        <Field label="Username">
          <input className={inputClass} autoComplete="off" spellCheck={false} value={username} onChange={(e) => setUsername(e.target.value)} />
        </Field>
        <Field label="Password" hint={`At least ${MIN_PASSWORD} characters`}>
          <input type="password" autoComplete="new-password" className={inputClass} value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Role">
          <select className={inputClass} value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
        </Field>
        <div className="flex flex-col gap-2">
          <span aria-hidden className="invisible hidden text-[13px] font-medium sm:block">
            &nbsp;
          </span>
          <Button variant="primary" disabled={!username.trim() || !password} onClick={() => void add()}>
            Add user
          </Button>
        </div>
      </div>
    </div>
  );
}

function ProvidersPart() {
  const { data, error } = useResource<AuthSettings>("/settings/auth");
  const [allowed, setAllowed] = useState<string>();
  const [providers, setProviders] = useState<ProviderDraft[]>();
  const [saves, setSaves] = useState(0);
  const [message, setMessage] = useState<Message>();
  const [busy, setBusy] = useState(false);
  const nextKey = useRef(0);

  const adopt = useCallback((view: AuthSettings) => {
    setAllowed(view.allowed_emails);
    setProviders(view.providers.map((p) => ({ ...p, key: nextKey.current++, secret: undefined })));
  }, []);
  useEffect(() => {
    if (data && providers === undefined) adopt(data);
  }, [data, providers, adopt]);

  if (!providers || allowed === undefined) {
    return error ? <Notice tone="error">{error}</Notice> : <p className="text-sm text-muted">Loading…</p>;
  }

  const patch = (key: number, change: Partial<ProviderDraft>) => setProviders((list) => list?.map((p) => (p.key === key ? { ...p, ...change } : p)));

  async function save() {
    setBusy(true);
    try {
      const view = await api.put<AuthSettings>("/settings/auth", {
        allowed_emails: allowed,
        providers: providers!.map(({ key: _key, client_secret: _set, source: _source, secret, ...p }) => ({ ...p, ...(secret !== undefined ? { client_secret: secret } : {}) })),
      });
      adopt(view);
      setSaves((n) => n + 1);
      setMessage({ tone: "success", text: "Saved" });
    } catch (err) {
      setMessage({ tone: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Result message={message} />
      <div className="flex flex-col gap-3.5">
        <Heading>Allowed e-mails (OIDC)</Heading>
        <Field label="Allowed e-mails (OIDC)" hint="One address per line. Local users are not affected.">
          <textarea className={`${inputClass} h-28 py-2 font-mono`} spellCheck={false} value={allowed} onChange={(e) => setAllowed(e.target.value)} />
        </Field>
      </div>
      <div className="flex flex-col gap-3.5">
        <Heading>OIDC providers</Heading>
        {providers.map((p) => (
          <div key={p.key} className="flex flex-col gap-3.5 rounded-lg border border-line p-3.5">
            <div className="grid gap-3.5 sm:grid-cols-2">
              <Field label="Provider id">
                <input className={`${inputClass} font-mono`} spellCheck={false} value={p.id} onChange={(e) => patch(p.key, { id: e.target.value })} />
              </Field>
              <Field label="Name">
                <input className={inputClass} value={p.name} onChange={(e) => patch(p.key, { name: e.target.value })} />
              </Field>
              <Field label="Discovery URL">
                <input className={`${inputClass} font-mono`} spellCheck={false} value={p.discovery_url} onChange={(e) => patch(p.key, { discovery_url: e.target.value })} />
              </Field>
              <Field label="Client id">
                <input className={`${inputClass} font-mono`} spellCheck={false} value={p.client_id} onChange={(e) => patch(p.key, { client_id: e.target.value })} />
              </Field>
              <SecretInput key={`${p.key}-${saves}`} label="Client secret" isSet={p.client_secret} onChange={(secret) => patch(p.key, { secret })} />
              <Field label="Scopes">
                <input className={`${inputClass} font-mono`} spellCheck={false} value={p.scopes} onChange={(e) => patch(p.key, { scopes: e.target.value })} />
              </Field>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Checkbox label="Enabled" checked={p.enabled} onChange={(e) => patch(p.key, { enabled: e.target.checked })} />
              <Button variant="danger" aria-label={`Remove provider ${p.id || "(new)"}`} onClick={() => setProviders((list) => list?.filter((x) => x.key !== p.key))}>
                Remove
              </Button>
            </div>
            {p.id && (
              <p className="text-[13px] text-muted">
                Callback URL for your IdP: <code className="font-mono">{`${location.origin}/api/auth/callback/${p.id}`}</code>
              </p>
            )}
          </div>
        ))}
        <div>
          <Button
            onClick={() =>
              setProviders((list) => [
                ...(list ?? []),
                { key: nextKey.current++, id: "", name: "", discovery_url: "", client_id: "", client_secret: false, scopes: "openid email profile", enabled: true },
              ])
            }
          >
            Add provider
          </Button>
        </div>
      </div>
      <div>
        <Button variant="primary" disabled={busy} onClick={() => void save()}>
          Save
        </Button>
      </div>
    </div>
  );
}

function ChangePasswordPart() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [message, setMessage] = useState<Message>();

  async function submit() {
    if (next.length < MIN_PASSWORD) return setMessage({ tone: "error", text: `Password must be at least ${MIN_PASSWORD} characters` });
    const res = await authClient.changePassword({ currentPassword: current, newPassword: next, revokeOtherSessions: true });
    if (res.error) return setMessage({ tone: "error", text: res.error.message ?? "Could not change the password" });
    setCurrent("");
    setNext("");
    setMessage({ tone: "success", text: "Password changed" });
  }

  return (
    <div className="flex flex-col gap-3.5">
      <Heading>Change my password</Heading>
      <Result message={message} />
      <div className="grid gap-3.5 sm:grid-cols-3 sm:items-end">
        <Field label="Current password">
          <input type="password" autoComplete="current-password" className={inputClass} value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        <Field label="New password" hint={`At least ${MIN_PASSWORD} characters`}>
          <input type="password" autoComplete="new-password" className={inputClass} value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Button variant="primary" disabled={!current || !next} onClick={() => void submit()}>
          Change password
        </Button>
      </div>
    </div>
  );
}

export function SignInSection() {
  const { data } = authClient.useSession();
  const user = data?.user as (Account & { source?: string | null }) | undefined;
  if (!user) return <p className="text-sm text-muted">Loading…</p>;
  return (
    <div id="sign-in" className={`flex flex-col gap-6 ${SCROLL_TARGET}`}>
      {user.role === "admin" && <UsersPart selfId={user.id} />}
      {user.role === "admin" && <ProvidersPart />}
      {user.source === "local" && <ChangePasswordPart />}
    </div>
  );
}
