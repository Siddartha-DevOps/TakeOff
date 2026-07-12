import "dotenv/config";
import path from "node:path";
import { defineConfig, env } from "prisma/config";

// Prisma 7 config. DATABASE_URL is loaded from .env via dotenv above (Prisma 7
// does not auto-load .env). The datasource URL lives here now (not in
// schema.prisma) and drives Migrate/introspection. `migrations.seed` wires
// `prisma db seed` to the tsx script so it doesn't rely on package.json#prisma.seed.
export default defineConfig({
  schema: path.join("prisma", "schema.prisma"),
  datasource: {
    url: env("DATABASE_URL"),
  },
  migrations: {
    path: path.join("prisma", "migrations"),
    seed: "tsx prisma/seed.ts",
  },
});
