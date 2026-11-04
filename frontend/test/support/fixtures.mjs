// 測試共用：讀真實 fixtures（staging r12 回應，勿改）
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));

export const FIXTURE_NAMES = ['walk_event', 'walk_plain', 'kin', 'direct', 'regnal'];

export function loadFixture(name) {
  return JSON.parse(readFileSync(join(HERE, '..', 'fixtures', `${name}.json`), 'utf8'));
}

export function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}
