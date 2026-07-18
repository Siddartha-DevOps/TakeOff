import "dotenv/config";
import { prisma } from "../lib/prisma";

// One read against the database to prove the connection + adapter + client wiring.
async function main() {
  const users = await prisma.user.count();
  const posts = await prisma.post.count();
  console.log(`✅ Connected — ${users} users, ${posts} posts`);
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (e) => {
    console.error("❌ Prisma connection failed:", e);
    await prisma.$disconnect();
    process.exit(1);
  });
