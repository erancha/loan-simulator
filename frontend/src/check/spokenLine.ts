/**
 * The sentence the chat shows for a person's message. A form sends a labelled line in the
 * person's name ("רכב: הלוואה בסך 45,000 ₪"), which the agent reads; the chat shows the sentence
 * the person could have typed. Anything else, what the person typed included, shows as it is.
 *
 * The code, not the model, recognises a line: each pattern comes from the composer in copy.ts that
 * writes the line, called with sample values whose places become the pattern's holes, so a change
 * to a composer's wording reaches its pattern by itself. A stored line keeps no mark of the form
 * that sent it, so the shape is what identifies it, in old checks and in the demo's recording too.
 */
import type { Question, QuestionField, ScenarioMovement } from '../api/types.ts'
import {
  amountCoveredLineOf,
  amountDeclinedLine,
  amountText,
  answerLine,
  CEILING_LABEL,
  cloneLine,
  confirmedReadingLineOf,
  confirmedTermLine,
  CONTINUE_TO_ANOTHER_OFFER,
  fieldLabel,
  offerLineOf,
  openingLine,
  PAYMENT_PLANNING,
  questionLabel,
  SCENARIO_FORM,
  scenarioLine,
  SKIP,
  skipLine,
  SPOKEN,
  STAY_CHOICE,
  termText,
  updateLine,
} from './copy.ts'

// Sample values whose written forms stand for a hole; none occurs in a composer's own words.
const TEXT = '①'
const LENDER = '②'
const AMOUNT = '987654'
const SHEKELS = amountText(AMOUNT)
const MONTHS = 77
const RISE = '9.87'

// What a hole may match: any text, a whole number of shekels, a count of months, a percentage.
const ANY = '.+?'
const SHEKEL_FIGURE = '[\\d,]+ ₪'
const DIGITS = '\\d+'
const PERCENT = '[\\d.]+'

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * The line a composer wrote from sample values, as a pattern whose named holes stand where the
 * samples were. Key: the hole's name; value: the sample as written and what the hole matches.
 */
function shapeOf(line: string, holes: Record<string, [sample: string, pattern: string]>): RegExp {
  let pattern = escape(line)
  for (const [name, [sample, match]] of Object.entries(holes)) {
    const at = escape(sample)
    if (!pattern.includes(at)) throw new Error(`the sample ${sample} is missing from "${line}"`)
    pattern = pattern.replace(at, `(?<${name}>${match})`)
  }
  return new RegExp(`^${pattern}$`, 's')
}

/** One form line: its shape, and the sentence its holes' values make. */
interface Form {
  shape: RegExp
  say: (holes: Record<string, string>) => string | null
}

const FIELD_SENTENCE: Partial<Record<QuestionField, (value: string) => string>> = {
  purpose: SPOKEN.purpose,
  amount: SPOKEN.amount,
  own_capital: SPOKEN.ownCapital,
  net_fixed_income: SPOKEN.income,
  fixed_expenses: SPOKEN.expenses,
  payment_ceiling: SPOKEN.ceiling,
}

// The track numbers the offer line puts before each track, "(1) ", "(2) " and so on.
const TRACK_NUMBER = /\s*\(\d+\)\s*/

// Ordered so that a line two shapes could take meets the narrower one first: a term or an amount
// confirmation before a reading's, whose hole takes anything after "אישור:".
const FORMS: Form[] = [
  {
    shape: shapeOf(openingLine(TEXT, AMOUNT), {
      purpose: [TEXT, ANY],
      amount: [SHEKELS, SHEKEL_FIGURE],
    }),
    say: ({ purpose, amount }) => SPOKEN.opening(purpose, amount),
  },
  {
    shape: shapeOf(answerLine(CEILING_LABEL, SHEKELS), { amount: [SHEKELS, SHEKEL_FIGURE] }),
    say: ({ amount }) => SPOKEN.ceiling(amount),
  },
  ...Object.entries(FIELD_SENTENCE).map(([field, sentence]) => ({
    shape: shapeOf(answerLine(fieldLabel(field as QuestionField), TEXT), { value: [TEXT, ANY] }),
    say: ({ value }: Record<string, string>) => sentence(value),
  })),
  {
    shape: shapeOf(confirmedTermLine(MONTHS, AMOUNT), {
      months: [String(MONTHS), DIGITS],
      amount: [SHEKELS, SHEKEL_FIGURE],
    }),
    say: ({ months, amount }) => SPOKEN.termWithCeiling(termText(Number(months)), amount),
  },
  {
    shape: shapeOf(confirmedTermLine(MONTHS, null), { months: [String(MONTHS), DIGITS] }),
    say: ({ months }) => SPOKEN.term(termText(Number(months))),
  },
  {
    shape: shapeOf(amountCoveredLineOf(LENDER, SHEKELS, TEXT), {
      amount: [SHEKELS, SHEKEL_FIGURE],
      lender: [LENDER, ANY],
      reading: [TEXT, '.+'],
    }),
    say: ({ lender, amount, reading }) => SPOKEN.covered(lender, amount, reading),
  },
  {
    shape: shapeOf(confirmedReadingLineOf(TEXT), { reading: [TEXT, '.+'] }),
    say: ({ reading }) => SPOKEN.readingConfirmed(reading),
  },
  {
    shape: shapeOf(amountDeclinedLine(LENDER, AMOUNT), {
      lender: [LENDER, ANY],
      amount: [SHEKELS, SHEKEL_FIGURE],
    }),
    say: ({ lender, amount }) => SPOKEN.declined(lender, amount),
  },
  {
    shape: shapeOf(skipLine(TEXT), { label: [TEXT, '.+'] }),
    say: () => SPOKEN.skipped,
  },
  {
    shape: shapeOf(updateLine(TEXT, AMOUNT), {
      label: [TEXT, ANY],
      amount: [SHEKELS, SHEKEL_FIGURE],
    }),
    // A label the data panel no longer shows has no sentence, so its line shows as stored.
    say: ({ label, amount }) => {
      const field = SPOKEN.updatedField[label]
      return field === undefined ? null : SPOKEN.updated(field, amount)
    },
  },
  {
    shape: shapeOf(offerLineOf(LENDER, TEXT, String(MONTHS)), {
      lender: [LENDER, ANY],
      tracks: [TEXT, '.+'],
      months: [String(MONTHS), DIGITS],
    }),
    say: ({ lender, tracks, months }) =>
      SPOKEN.offer(lender, tracks.split(TRACK_NUMBER).filter(Boolean).map(SPOKEN.track), months),
  },
  {
    shape: shapeOf(cloneLine(TEXT), { request: [TEXT, '.+'] }),
    say: ({ request }) => SPOKEN.clone(request),
  },
  ...(Object.keys(SCENARIO_FORM) as ScenarioMovement[]).map((movement) => ({
    shape: shapeOf(scenarioLine(movement, RISE), { rise: [RISE, PERCENT] }),
    say: ({ rise }: Record<string, string>) =>
      SPOKEN.scenario(SCENARIO_FORM[movement].subject, rise),
  })),
]

/** Key: a line a button sends as it is; value: its sentence. */
const FIXED_LINES: Record<string, string> = {
  [SKIP]: SPOKEN.skipped,
  [PAYMENT_PLANNING]: SPOKEN.paymentPlanning,
  [CONTINUE_TO_ANOTHER_OFFER]: SPOKEN.anotherOffer,
  [STAY_CHOICE]: SPOKEN.stay,
}

/** A question the agent worded itself, which neither a field nor a card nor the clone offer is. */
function isFreeQuestion(question: Question): boolean {
  return question.kind === undefined && question.field === null && question.offer_clone !== true
}

/**
 * The sentence for a person's message; asked is the latest question above it in the chat, whose
 * answer line carries the question before the answer.
 */
export function spokenLine(text: string, asked: Question | null): string {
  const fixed = FIXED_LINES[text]
  if (fixed !== undefined) return fixed
  for (const form of FORMS) {
    const groups = form.shape.exec(text)?.groups
    if (groups === undefined) continue
    const sentence = form.say(groups)
    if (sentence !== null) return sentence
  }
  // An answer to the agent's own question: the answer alone, since the question shows above it.
  if (asked !== null && isFreeQuestion(asked)) {
    const prefix = answerLine(questionLabel(asked), '')
    if (text.startsWith(prefix)) return text.slice(prefix.length)
  }
  return text
}
