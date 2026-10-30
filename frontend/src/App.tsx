import { SignInButton } from './auth/SignInButton.tsx'
import { useSession } from './auth/useSession.ts'
import { CHECKING_SESSION, serverUnreachable } from './copy.ts'
import { Landing } from './Landing.tsx'
import { Shell } from './shell/Shell.tsx'

document.documentElement.lang = 'he'
document.documentElement.dir = 'rtl'

export function App() {
  const { session, signOut } = useSession()
  switch (session.state) {
    case 'loading':
      return (
        <Landing>
          <p className="muted">{CHECKING_SESSION}</p>
        </Landing>
      )
    case 'failed':
      return (
        <Landing>
          <p role="alert" className="error">
            {serverUnreachable(session.message)}
          </p>
        </Landing>
      )
    case 'signed-out':
      return (
        <Landing pitch>
          <SignInButton refusal={session.refusal} />
        </Landing>
      )
    case 'signed-in':
      return <Shell user={session.user} onSignOut={signOut} />
  }
}
