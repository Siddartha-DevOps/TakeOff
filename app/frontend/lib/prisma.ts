import { PrismaClient } from "../generated/prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";

// Server-side only — never import this into a browser/client component.
// Prisma 7 requires a driver adapter: PrismaPg opens a direct pg connection
// using DATABASE_URL (written to .env by `npx prisma postgres link`).
// A singleton avoids exhausting the connection pool on dev hot-reload.
const connectionString = process.env.DATABASE_URL;
if (!connectionString) {
  throw new Error(
    "DATABASE_URL is not set. Run `npx prisma postgres link` (writes it to .env) or set it in the environment.",
  );
}

const adapter = new PrismaPg({ connectionString });

const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

export const prisma = globalForPrisma.prisma ?? new PrismaClient({ adapter });

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}
