/**
 * event-hub: Valkey sub 이벤트 집계 + 다른 앱 REST 트리거 (Node.js / Express)
 *
 * - Valkey SUBSCRIBE: crud-events 채널 → 메모리 내 최근 100건 유지
 * - GET  /events          : 수신된 이벤트 목록
 * - GET  /dashboard       : 앱·액션별 이벤트 집계 통계
 * - POST /trigger/:target : mongo-crud 또는 pg-crud 에 POST /items, /records 호출
 * - GET  /health          : 헬스체크
 *
 * 환경변수
 *   VALKEY_HOST     : valkey-production.middleware.svc.cluster.local
 *   VALKEY_PORT     : 6379
 *   VALKEY_PASSWORD : (선택) auth.enabled 시 필수
 *   MONGO_CRUD_URL  : http://mongo-crud.workload.svc.cluster.local
 *   PG_CRUD_URL     : http://pg-crud.workload.svc.cluster.local
 *   MISSION         : "" | dns-fail | oom
 */

'use strict';

const express = require('express');
const { createClient } = require('redis');

// ---------------------------------------------------------------------------
// 설정
// ---------------------------------------------------------------------------
const VALKEY_HOST     = process.env.VALKEY_HOST || 'localhost';
const VALKEY_PORT     = process.env.VALKEY_PORT || '6379';
const VALKEY_PASSWORD = process.env.VALKEY_PASSWORD || '';
const MISSION         = process.env.MISSION || '';

// MISSION: dns-fail → 잘못된 서비스명으로 연결 유발
const MONGO_CRUD_URL = MISSION === 'dns-fail'
  ? 'http://mongo-crud-INVALID.workload.svc.cluster.local'
  : (process.env.MONGO_CRUD_URL || 'http://mongo-crud.workload.svc.cluster.local');

const PG_CRUD_URL = MISSION === 'dns-fail'
  ? 'http://pg-crud-INVALID.workload.svc.cluster.local'
  : (process.env.PG_CRUD_URL || 'http://pg-crud.workload.svc.cluster.local');

// ---------------------------------------------------------------------------
// 이벤트 저장소 (메모리 내 최근 100건)
// ---------------------------------------------------------------------------
const MAX_EVENTS = 100;
const events = [];
const stats = { total: 0, bySource: {}, byAction: {} };

function storeEvent(raw) {
  try {
    const evt = JSON.parse(raw);
    events.unshift(evt);
    if (events.length > MAX_EVENTS) events.length = MAX_EVENTS;

    stats.total++;
    stats.bySource[evt.source] = (stats.bySource[evt.source] || 0) + 1;
    stats.byAction[evt.action] = (stats.byAction[evt.action] || 0) + 1;
  } catch (e) {
    console.warn('[WARN] event parse failed:', e.message);
  }
}

// ---------------------------------------------------------------------------
// Valkey Subscriber
// ---------------------------------------------------------------------------
const subscriber = createClient({
  socket: { host: VALKEY_HOST, port: parseInt(VALKEY_PORT) },
  ...(VALKEY_PASSWORD && { password: VALKEY_PASSWORD }),
});

subscriber.on('error', (err) => console.error('[Valkey subscriber]', err));

async function startSubscriber() {
  await subscriber.connect();
  await subscriber.subscribe('crud-events', (message) => {
    storeEvent(message);
  });
  console.log(`[INFO] Subscribed to crud-events @ ${VALKEY_HOST}:${VALKEY_PORT}`);
}

// ---------------------------------------------------------------------------
// Express App
// ---------------------------------------------------------------------------
const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ status: 'ok', mission: MISSION, eventCount: events.length });
});

app.get('/events', (req, res) => {
  const limit = parseInt(req.query.limit || '20');
  res.json(events.slice(0, limit));
});

app.get('/dashboard', (req, res) => {
  res.json({
    stats,
    recentEvents: events.slice(0, 10),
  });
});

/**
 * POST /trigger/:target
 * target: mongo | pg
 * 각 앱에 새 레코드 삽입 요청을 보냄
 */
app.post('/trigger/:target', async (req, res) => {
  // MISSION: oom → 대형 버퍼 할당
  if (MISSION === 'oom') {
    const bufs = [];
    for (let i = 0; i < 50; i++) bufs.push(Buffer.alloc(10 * 1024 * 1024));
  }

  const { target } = req.params;
  let url, body;

  if (target === 'mongo') {
    url  = `${MONGO_CRUD_URL}/items`;
    body = { name: 'triggered-' + Date.now(), value: 'from event-hub' };
  } else if (target === 'pg') {
    url  = `${PG_CRUD_URL}/records`;
    body = { name: 'triggered-' + Date.now(), value: 'from event-hub' };
  } else {
    return res.status(400).json({ error: 'unknown target, use "mongo" or "pg"' });
  }

  try {
    const resp = await fetch(url, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
      signal:  AbortSignal.timeout(5000),
    });
    const data = await resp.json();
    res.json({ target, status: resp.status, data });
  } catch (err) {
    console.error(`[ERROR] trigger ${target}:`, err.message);
    res.status(502).json({ error: err.message, target });
  }
});

// ---------------------------------------------------------------------------
// 기동
// ---------------------------------------------------------------------------
const PORT = process.env.PORT || 8080;

startSubscriber()
  .then(() => {
    app.listen(PORT, () => console.log(`[INFO] event-hub listening on :${PORT}  MISSION=${MISSION}`));
  })
  .catch((err) => {
    console.error('[FATAL] Valkey connect failed:', err);
    process.exit(1);
  });
