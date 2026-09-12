import "dotenv/config";
import { prisma } from "../lib/prisma";

// Idempotent seed (upsert) so `prisma db seed` can be re-run safely.
async function main() {
  const alice = await prisma.user.upsert({
    where: { email: "alice@example.com" },
    update: {},
    create: {
      email: "alice@example.com",
      name: "Alice",
      posts: { create: [{ title: "Hello Prisma Postgres", published: true }] },
    },
  });

  const bob = await prisma.user.upsert({
    where: { email: "bob@example.com" },
    update: {},
    create: {
      email: "bob@example.com",
      name: "Bob",
      posts: {
        create: [
          { title: "Draft idea", published: false },
          { title: "Shipped feature", published: true },
        ],
      },
    },
  });

  console.log(`🌱 Seeded users: ${alice.email}, ${bob.email}`);
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (e) => {
    console.error(e);
    await prisma.$disconnect();
    process.exit(1);
  });
