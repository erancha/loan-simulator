import { render, screen } from '@testing-library/react'
import { useState } from 'react'
import { expect, test } from 'vitest'
import { fillBox } from './fillBox.ts'

/** A controlled box, as the page's composer and question boxes are. */
function Box() {
  const [value, setValue] = useState('')
  return <input aria-label="הכנסה קבועה" value={value} onChange={(e) => setValue(e.target.value)} />
}

test('fills a controlled box by its label through React, and the returned call empties it', () => {
  render(<Box />)
  const clear = fillBox({ box: 'הכנסה קבועה', value: '8,300' })
  expect(screen.getByRole('textbox', { name: 'הכנסה קבועה' })).toHaveValue('8,300')

  clear()
  expect(screen.getByRole('textbox', { name: 'הכנסה קבועה' })).toHaveValue('')
})

test('a box missing from the page throws, naming it', () => {
  expect(() => fillBox({ box: 'אין כזה', value: '1' })).toThrow('אין כזה')
})
