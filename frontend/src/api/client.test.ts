import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  confirmReading,
  saveFinances,
  sendOpening,
  sendTermConfirmation,
  sendUnanswered,
} from './checks.ts'
import { ApiException, SIGNED_OUT_EVENT, apiDelete, apiGet, apiPost, apiPut } from './client.ts'

function respond(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(body === undefined ? null : JSON.stringify(body), { status }),
    ),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('client', () => {
  it('turns an error body into an ApiException carrying status and detail', async () => {
    respond(409, { detail: 'turn running', check_id: 'c1' })
    const error = await apiPost('/x', {}).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiException)
    expect(error).toMatchObject({ status: 409, message: 'turn running', detail: { check_id: 'c1' } })
  })

  it('exposes next_allowed of a 429 on the detail', async () => {
    respond(429, { detail: 'limit reached', next_allowed: '2026-10-29T10:00:00+00:00' })
    const error = await apiPost('/x', {}).catch((e: unknown) => e)
    expect(error).toMatchObject({
      status: 429,
      message: 'limit reached',
      detail: { next_allowed: '2026-10-29T10:00:00+00:00' },
    })
  })

  it('reads a request validation list as refused data and logs its messages', async () => {
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
    const detail = [{ loc: ['body', 'text'], msg: 'String should have at least 1 character' }]
    respond(422, { detail })
    await expect(apiPost('/x', {})).rejects.toThrow('הנתונים לא התקבלו')
    expect(logged).toHaveBeenCalledWith('request rejected', detail)
    logged.mockRestore()
  })

  it('names the status in Hebrew when the server gives no detail', async () => {
    respond(500, { error: 'boom' })
    await expect(apiGet('/x')).rejects.toThrow('הבקשה נכשלה (קוד 500)')
    respond(502, undefined)
    await expect(apiGet('/x')).rejects.toThrow('הבקשה נכשלה (קוד 502)')
  })

  it('uses a string detail as the message', async () => {
    respond(404, { detail: 'no such check' })
    await expect(apiGet('/x')).rejects.toThrow('no such check')
  })

  it('sends DELETE', async () => {
    respond(204, undefined)
    await expect(apiDelete('/x')).resolves.toBeUndefined()
    expect(fetch).toHaveBeenCalledWith('/x', expect.objectContaining({ method: 'DELETE' }))
  })

  it('returns undefined for 204', async () => {
    respond(204, undefined)
    await expect(apiPost('/x', {})).resolves.toBeUndefined()
  })

  it('returns undefined for a 202 with an empty body', async () => {
    respond(202, undefined)
    await expect(apiPost('/x', { text: 'hi' })).resolves.toBeUndefined()
  })

  it('announces a 401 on window so the page can drop to sign-in', async () => {
    const heard = vi.fn()
    window.addEventListener(SIGNED_OUT_EVENT, heard)
    respond(401, { detail: 'sign in to continue' })
    const error = await apiGet('/x').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiException)
    expect(error).toMatchObject({ status: 401 })
    expect(heard).toHaveBeenCalledOnce()
    respond(404, { detail: 'nope' })
    await expect(apiGet('/x')).rejects.toThrow('nope')
    expect(heard).toHaveBeenCalledOnce()
    window.removeEventListener(SIGNED_OUT_EVENT, heard)
  })

  it('posts the body as JSON', async () => {
    respond(201, { id: 'c1' })
    await apiPost('/x', { a: 1 })
    expect(fetch).toHaveBeenCalledWith('/x', expect.objectContaining({ method: 'POST', body: '{"a":1}' }))
  })

  it('puts the body as JSON', async () => {
    respond(200, { ok: true })
    await apiPut('/x', { a: 1 })
    expect(fetch).toHaveBeenCalledWith(
      '/x',
      expect.objectContaining({
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: '{"a":1}',
      }),
    )
  })
})

describe('saveFinances', () => {
  it("saveFinances puts decimal strings to the check's finances", async () => {
    const saved = { id: 'c1', finances: { net_fixed_income: '9300', fixed_expenses: '4500.50' } }
    respond(200, saved)
    const update = { net_fixed_income: '9300', fixed_expenses: '4500.50' }
    await expect(saveFinances('c1', update)).resolves.toEqual(saved)
    expect(fetch).toHaveBeenCalledWith(
      '/api/checks/c1/finances',
      expect.objectContaining({
        method: 'PUT',
        body: '{"net_fixed_income":"9300","fixed_expenses":"4500.50"}',
      }),
    )
  })

  it('sends only the figure named', async () => {
    respond(200, {})
    await saveFinances('c1', { fixed_expenses: '4000' })
    expect(fetch).toHaveBeenCalledWith(
      '/api/checks/c1/finances',
      expect.objectContaining({ body: '{"fixed_expenses":"4000"}' }),
    )
  })
})

describe('the offers-first calls', () => {
  it('each new call reaches its route with its body', async () => {
    const reaches = async (
      call: () => Promise<void>,
      url: string,
      method: string,
      body: unknown,
    ) => {
      respond(202, undefined)
      await call()
      expect(fetch).toHaveBeenCalledWith(
        url,
        expect.objectContaining({ method, body: JSON.stringify(body) }),
      )
    }
    await reaches(
      () => sendOpening('c1', 'רכב', 'רכב', '45000'),
      '/api/checks/c1/opening',
      'POST',
      { text: 'רכב', purpose: 'רכב', amount: '45000' },
    )
    await reaches(
      () => sendTermConfirmation('c1', 'אישור'),
      '/api/checks/c1/term-confirmation',
      'POST',
      { text: 'אישור' },
    )
    await reaches(() => sendUnanswered('c1', 'דילוג'), '/api/checks/c1/unanswered', 'POST', {
      text: 'דילוג',
    })
    await reaches(
      () => confirmReading('c1', 'a-1', 'fixed_unlinked'),
      '/api/checks/c1/awaiting-offers/a-1',
      'PUT',
      { reading: 'fixed_unlinked' },
    )
  })
})
