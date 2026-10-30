/** Remembers, in this browser, the local day the person last tapped the market-data sample. */
const STORAGE_KEY = 'market-sample-tapped'

const today = () => new Date().toLocaleDateString('en-CA')

export function marketSampleTappedToday(): boolean {
  return localStorage.getItem(STORAGE_KEY) === today()
}

export function rememberMarketSampleTapped(): void {
  localStorage.setItem(STORAGE_KEY, today())
}
