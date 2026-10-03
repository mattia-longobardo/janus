// Creates or updates the better-auth tables in the Postgres schema `auth`.
// Runs once at container start, before the API. Idempotent.
// The schema-affecting options below must match lib/auth/server.ts.
import { betterAuth } from "better-auth";
import { getMigrations } from "better-auth/db/migration";
import { admin, username } from "better-auth/plugins";
import pg from "pg";

const url = process.env.AUTH_DATABASE_URL || process.env.JANUS_DATABASE_URL?.replace(/^postgresql\+\w+:/, "postgresql:");
if (!url) {
  console.error("migrate-auth: set AUTH_DATABASE_URL (or JANUS_DATABASE_URL)");
  process.exit(1);
}

const bootstrap = new pg.Client({ connectionString: url });
await bootstrap.connect();
await bootstrap.query("CREATE SCHEMA IF NOT EXISTS auth");
await bootstrap.end();

const pool = new pg.Pool({ connectionString: url, options: "-c search_path=auth" });
const auth = betterAuth({
  database: pool,
  secret: process.env.AUTH_SECRET,
  baseURL: process.env.AUTH_URL,
  emailAndPassword: { enabled: true },
  user: { additionalFields: { source: { type: "string", defaultValue: "oidc", input: false } } },
  plugins: [username(), admin({ defaultRole: "user" })],
});

const { toBeCreated, toBeAdded, toBeAddedIndexes, runMigrations } = await getMigrations(auth.options);
if (toBeCreated.length || toBeAdded.length || toBeAddedIndexes.length) {
  await runMigrations();
  console.log(`migrate-auth: created ${toBeCreated.length} table(s), altered ${toBeAdded.length}, indexed ${toBeAddedIndexes.length}`);
}

// Optional bootstrap admin, only on an empty user table.
const { JANUS_ADMIN_USERNAME: name, JANUS_ADMIN_PASSWORD: password } = process.env;
if (name && password) {
  const { rows } = await pool.query('SELECT count(*)::int AS n FROM "user"');
  if (rows[0].n === 0) {
    await auth.api.createUser({
      body: { email: `${name}@local.invalid`, password, name, role: "admin", data: { username: name, source: "local" } },
    });
    console.log(`migrate-auth: created admin "${name}"`);
  }
}
await pool.end();
