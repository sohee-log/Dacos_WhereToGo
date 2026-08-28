// lib/session.ts
const KEY = 'wheretogo.user_id';

export function saveUserId(id: string) {
  try { localStorage.setItem(KEY, id); } catch { /* 프라이빗 모드 등 — 무시 */ }
}

export function loadUserId(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function clearUserId() {
  try { localStorage.removeItem(KEY); } catch { /* 무시 */ }
}