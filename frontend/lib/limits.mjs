// 限流、併發額度、連線數上限、Host 白名單。
//
// 送進 backend 的問題上限（單 GPU）。
// 實測（2026-11-04，staging r12）：客戶端中途斷線後 backend 仍把生成跑完，vLLM 記的是 stop 不是 abort，
// 所以額度要等 backend 真的回來才還，跟著客戶端一起還的話 GPU 上會超過上限。
// 額度滿時：佔著的都有人在等 → 拒絕（429）；其中有人已經走了 → 新題目排隊等它跑完，讀者不必重試。
// 排隊有上限、一個 IP 只佔一席，也有最久等候時間（backend 卡住時不會無限等）。

import { isIP } from 'node:net';

const RATE_WINDOW_MS = 60_000;
const MAX_TRACKED_IPS = 10_000;
const REFUSAL_LOG_INTERVAL_MS = 60_000;

/** 滑動視窗限流。放行回 0，否則回還要等幾秒。 */
export function createRateLimiter({ limit, now }) {
  const hits = new Map();
  const sweep = (cutoff) => {
    for (const [ip, times] of hits) {
      if (times[times.length - 1] <= cutoff) hits.delete(ip);
    }
  };
  return function take(ip) {
    const at = now();
    const cutoff = at - RATE_WINDOW_MS;
    if (hits.size > MAX_TRACKED_IPS) sweep(cutoff);
    const recent = (hits.get(ip) ?? []).filter((time) => time > cutoff);
    if (recent.length >= limit) {
      hits.set(ip, recent);
      return Math.ceil((recent[0] - cutoff) / 1000);
    }
    hits.set(ip, [...recent, at]);
    return 0;
  };
}

/** 讀者還在不在：連線在回應送完之前關掉就算走了。 */
export function watchClient(req, res) {
  const client = {
    gone: req.socket.destroyed,
    onGone: (listener) => res.once('close', listener),
  };
  res.once('close', () => {
    client.gone = !res.writableFinished;
  });
  return client;
}

/** createAskGate({limit, maxWaiters, maxWaitMs}) → {canEnter(ip), enter(ip, client)}。
 *  client 是 {gone:boolean, onGone(listener)}。 */
export function createAskGate({ limit, maxWaiters, maxWaitMs }) {
  const running = new Set();
  let waiters = [];

  const occupy = (client) => {
    running.add(client);
    return () => {
      running.delete(client);
      const [next, ...rest] = waiters;
      if (!next) return;
      waiters = rest;
      next.admit();
    };
  };

  const hasRoomInQueue = (ip) => waiters.length < maxWaiters && !waiters.some((waiter) => waiter.ip === ip);

  return {
    canEnter(ip) {
      if (running.size < limit) return true;
      return [...running].some((client) => client.gone) && hasRoomInQueue(ip);
    },

    /** 回傳 release 函式；排隊時讀者走了或等太久回 null。 */
    enter(ip, client) {
      if (running.size < limit) return Promise.resolve(occupy(client));
      return new Promise((resolve) => {
        const waiter = { ip, admit: () => settle(occupy(client)) };
        const timer = setTimeout(() => settle(null), maxWaitMs);
        function settle(outcome) {
          clearTimeout(timer);
          waiters = waiters.filter((item) => item !== waiter);
          resolve(outcome);
        }
        client.onGone(() => settle(null));
        waiters = [...waiters, waiter];
      });
    },
  };
}

/** 連線數上限：限流只算完成的請求，半開連線完全不計，所以另外擋。超過就直接關，不回應也不讀內容。
 *  被打的時候 log 不能跟著灌爆：一分鐘最多一行，只寫原因。 */
export function guardConnections(server, { maxConnections, maxPerIp, now, onRefuse }) {
  const open = new Map();
  let lastLoggedAt = -Infinity;
  const refused = () => {
    if (now() - lastLoggedAt < REFUSAL_LOG_INTERVAL_MS) return;
    lastLoggedAt = now();
    onRefuse();
  };
  server.maxConnections = maxConnections;
  server.on('drop', refused);
  server.on('connection', (socket) => {
    const ip = socket.remoteAddress;
    const count = (open.get(ip) ?? 0) + 1;
    if (count > maxPerIp) {
      refused();
      socket.destroy();
      return;
    }
    open.set(ip, count);
    socket.once('close', () => {
      const left = open.get(ip) - 1;
      if (left > 0) open.set(ip, left);
      else open.delete(ip);
    });
  });
}

/** 擋 DNS rebinding：rebinding 後 Origin 與 Host 都是攻擊者的網域，同站檢查攔不住，但網域一定不在這份名單上。
 *  IP 字面值一定放行（rebinding 一定用網域），所以區網用 IP 連不必設定。 */
export function isAllowedHost(hostHeader, allowedHosts = []) {
  const hostname = hostnameOf(hostHeader);
  if (!hostname) return false;
  return hostname === 'localhost' || isIP(hostname.replace(/^\[|\]$/g, '')) !== 0 || allowedHosts.includes(hostname);
}

function hostnameOf(hostHeader) {
  if (!hostHeader) return null;
  try {
    return new URL(`http://${hostHeader}`).hostname;
  } catch {
    return null;
  }
}
