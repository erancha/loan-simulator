import { expect, test } from 'vitest'
import { MARKET_SAMPLE } from './copy.ts'
import { isMarketSample } from './marketSample.ts'

const SAMPLE = MARKET_SAMPLE.text

test('the sample as tapped, with the trailing space the chip adds, is the sample', () => {
  expect(isMarketSample(`${SAMPLE} `)).toBe(true)
})

test('spacing, line breaks and the closing punctuation do not matter', () => {
  expect(isMarketSample(SAMPLE.replaceAll('\n', '  ').replace(/\?$/, ''))).toBe(true)
  expect(isMarketSample(`  ${SAMPLE.replace(/\?$/, '.')}\n`)).toBe(true)
  expect(isMarketSample(`${SAMPLE}!!`)).toBe(true)
})

test('a changed wording is not the sample', () => {
  expect(isMarketSample(SAMPLE.replace('5 השנים', '10 השנים'))).toBe(false)
  expect(isMarketSample(`${SAMPLE} ומה צפוי בשנה הבאה?`)).toBe(false)
})
