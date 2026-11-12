// Writes ../data/users.json: USERS accounts with bcrypt hashes at cost 10 (both servers read the same file).
// usage: node make_users.mjs [COUNT=100]
import { writeFileSync } from 'node:fs';
import bcrypt from 'bcryptjs';

const COUNT = Number(process.argv[2] ?? 100);
const COST = 10;
const users = [];
for (let id = 1; id <= COUNT; id++) {
  users.push({ id, email: `user${id}@example.com`, hash: bcrypt.hashSync(`password-${id}`, COST) });
}
writeFileSync(new URL('../data/users.json', import.meta.url), `${JSON.stringify(users, null, 1)}\n`);
console.log(`${COUNT} users, cost ${COST}`);
