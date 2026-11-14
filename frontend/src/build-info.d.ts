// Set at build time by buildInfo.ts through the Vite and Vitest configs.
// MAJOR.MINOR.COMMITS: the release tag the page's checkout descends from and the commits since it.
declare const __APP_VERSION__: string
// The date of that checkout's last commit, DD/MM/YYYY.
declare const __APP_COMMIT_DATE__: string
