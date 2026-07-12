import "dotenv/config";
import path from "node:path";
import { defineConfig } from "prisma/config";

// Prisma 7 config. DATABASE_URL is loaded from .env via dotenv above (Prisma 7
// does not auto-load .env). The datasource URL lives here now (not in
// schema.prisma) and drives Migrate/introspection. We read it via
// `process.env` (not the `env()` helper) so that `prisma postgres link` — which
// runs *before* DATABASE_URL exists to write it — doesn't fail on a missing
// variable. `migrations.seed` wires `prisma db seed` to the tsx script.
export default defineConfig({
  schema: path.join("prisma", "schema.prisma"),
  datasource: {
    url: process.env.DATABASE_URL,
  },
  migrations: {
    path: path.join("prisma", "migrations"),
    seed: "tsx prisma/seed.ts",
  },
});
