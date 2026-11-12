// The login API in Node: Express, one route that checks a password against its stored bcrypt hash.
// The entry files pick the bcrypt library: server-bcryptjs.mjs (pure JavaScript) or server-bcrypt.mjs (C++ addon).
import { readFileSync } from 'node:fs';
import os from 'node:os';
import express from 'express';

export function serve(bcrypt, name) {
  const port = Number(process.env.PORT ?? 8080);
  const rows = JSON.parse(readFileSync(process.env.USERS ?? '../data/users.json', 'utf8'));
  const users = new Map(rows.map((u) => [u.email, u]));
  const app = express();
  app.use(express.json());

  app.get('/health', (req, res) => {
    res.type('text').send('ok');
  });

  app.post('/login', async (req, res) => {
    const { email, password } = req.body ?? {};
    const user = users.get(email);
    if (!user || typeof password !== 'string') {
      res.status(401).json({ ok: false });
      return;
    }
    const ok = await bcrypt.compare(password, user.hash);
    if (!ok) {
      res.status(401).json({ ok: false });
      return;
    }
    res.json({ ok: true, id: user.id });
  });

  app.listen(port, '127.0.0.1', () => {
    const pool = process.env.UV_THREADPOOL_SIZE ?? 'default (4)';
    console.log(`node ${process.version}, ${name}, UV_THREADPOOL_SIZE=${pool}, availableParallelism ${os.availableParallelism()}`);
  });
}
