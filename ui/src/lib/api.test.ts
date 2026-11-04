import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, authHeaders, detectRole, getKey, setKey } from './api';

const json = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('api client', () => {
  it('stores the key in sessionStorage and sends it as X-Router-Key', () => {
    setKey('abc');
    expect(getKey()).toBe('abc');
    expect(authHeaders()).toEqual({ 'X-Router-Key': 'abc' });
    setKey('');
    expect(authHeaders()).toEqual({});
  });

  it('surfaces the server error message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(409, { error: 'provider still has accounts' })));
    await expect(api('DELETE', '/admin/providers/x')).rejects.toMatchObject({
      status: 409,
      message: 'provider still has accounts',
    });
    await expect(api('DELETE', '/admin/providers/x')).rejects.toBeInstanceOf(ApiError);
  });

  it('sends JSON bodies and handles 204', async () => {
    const f = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', f);
    setKey('k');
    expect(await api('PATCH', '/admin/x', { a: 1 })).toBeUndefined();
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.body).toBe('{"a":1}');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect((init.headers as Record<string, string>)['X-Router-Key']).toBe('k');
  });

  it('detects admin, read and none roles', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(200)));
    expect(await detectRole('a')).toBe('admin');
    vi.stubGlobal('fetch', vi.fn(async (u: string) => (u === '/admin/config' ? json(403) : json(200))));
    expect(await detectRole('r')).toBe('read');
    vi.stubGlobal('fetch', vi.fn(async () => json(401)));
    expect(await detectRole('bad')).toBe('none');
  });
});
