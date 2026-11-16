/**
 * Recognises the two chip sentences the server answers without the model, so the page sends
 * each to its own route: the market-data sample and the offer chip's sentence.
 */
import { MARKET_SAMPLE, OFFER_SAMPLE } from './copy.ts'

/** Spacing and the closing punctuation do not change what is asked. */
function normalised(text: string): string {
  return text.replace(/\s+/g, ' ').trim().replace(/[.?!\s]+$/, '')
}

const MARKET = normalised(MARKET_SAMPLE.text)
const OFFER = normalised(OFFER_SAMPLE.text)

/** Whether the person sends the market-data sample as given, apart from spacing and a closing
 * period, question mark or exclamation mark; any other wording goes to the model. */
export function isMarketSample(text: string): boolean {
  return normalised(text) === MARKET
}

/** Whether the text is the offer chip's sentence, by the same measure; an offer described in
 * any other words goes to the model, which opens the form itself. */
export function isOfferSample(text: string): boolean {
  return normalised(text) === OFFER
}
