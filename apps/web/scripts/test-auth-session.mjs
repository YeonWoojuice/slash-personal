import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import { transformWithOxc } from 'vite'

const source = await readFile(new URL('../src/lib/authSession.ts', import.meta.url), 'utf8')
const compiled = (await transformWithOxc(source, 'authSession.ts', { lang: 'ts' })).code
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
const {
  AUTH_LOGOUT_EVENT_KEY,
  endClientSession,
  isClientLogoutStorageEvent,
  legacyOidcUserStorageKey,
  signalClientLogout,
} = await import(moduleUrl)

assert.equal(
  legacyOidcUserStorageKey('https://issuer.example/pool', 'client-id'),
  'oidc.user:https://issuer.example/pool:client-id',
)

{
  const entries = new Map()
  signalClientLogout({ setItem: (key, value) => entries.set(key, value) }, 'event-1')
  assert.equal(entries.get(AUTH_LOGOUT_EVENT_KEY), 'event-1')
  assert.equal(
    isClientLogoutStorageEvent({ key: AUTH_LOGOUT_EVENT_KEY, newValue: 'event-1' }),
    true,
  )
  assert.equal(isClientLogoutStorageEvent({ key: 'other', newValue: 'event-1' }), false)
  assert.doesNotThrow(() =>
    signalClientLogout(
      {
        setItem: () => {
          throw new Error('storage blocked')
        },
      },
      'event-2',
    ),
  )
}

async function runSessionEnd({ revokeFails = false, removeFails = false } = {}) {
  const calls = []
  const result = endClientSession({
    revokeRefreshToken: async () => {
      calls.push('revoke')
      if (revokeFails) throw new Error('sensitive revoke error')
    },
    removeUser: async () => {
      calls.push('remove')
      if (removeFails) throw new Error('remove failed')
    },
    redirectToLogout: () => calls.push('redirect'),
  })
  return { calls, result }
}

{
  const { calls, result } = await runSessionEnd()
  await result
  assert.deepEqual(calls, ['revoke', 'remove', 'redirect'])
}

{
  const { calls, result } = await runSessionEnd({ revokeFails: true })
  await result
  assert.deepEqual(calls, ['revoke', 'remove', 'redirect'])
}

{
  const { calls, result } = await runSessionEnd({ removeFails: true })
  await assert.rejects(result, /remove failed/)
  assert.deepEqual(calls, ['revoke', 'remove', 'redirect'])
}

console.log('4 auth session tests passed')
