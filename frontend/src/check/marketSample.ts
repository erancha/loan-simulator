import { MARKET_SAMPLE } from './copy.ts'

/** Spacing and the closing punctuation do not change what is asked. */
function normalised(text: string): string {
  return text.replace(/\s+/g, ' ').trim().replace(/[.?!\s]+$/, '')
}

const SAMPLE = normalised(MARKET_SAMPLE.text)

/** Whether the person sends the market-data sample as given, apart from spacing and a closing
 * period, question mark or exclamation mark; any other wording goes to the model. */
export function isMarketSample(text: string): boolean {
  return normalised(text) === SAMPLE
}
