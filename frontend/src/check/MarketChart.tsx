import type { ChartShown } from '../api/types.ts'
import { formatMonth } from '../money.ts'
import { CHART_MONTH, CHART_TITLE, CHART_VALUE, chartSource } from './copy.ts'

const WIDTH = 600
const HEIGHT = 220
const LEFT = 48
const RIGHT = 12
const TOP = 12
const BOTTOM = 28

/** A percent for an axis label; the points' own labels keep the engine's decimal strings. */
function percent(value: number): string {
  return `${value.toLocaleString('he-IL', { maximumFractionDigits: 2 })}%`
}

/**
 * Draws a market series in the conversation: the prime as a line, the CPI's monthly change as
 * bars around zero. The vertical axis always includes zero, so a bar's height is its size. Each
 * point names its month and value on hover, and a hidden table carries the values for screen
 * readers.
 */
export function MarketChart({ chart }: { chart: ChartShown }) {
  const { series, points } = chart
  const values = points.map((point) => Number(point.value))
  const low = Math.min(0, ...values)
  const high = Math.max(0, ...values)
  const span = high - low || 1
  const plotWidth = WIDTH - LEFT - RIGHT
  const plotHeight = HEIGHT - TOP - BOTTOM
  const slot = plotWidth / points.length
  const x = (index: number) => LEFT + slot * (index + 0.5)
  const y = (value: number) => TOP + ((high - value) / span) * plotHeight
  const hover = (index: number) => `${formatMonth(points[index].month)}: ${points[index].value}%`
  const first = points[0].month
  const last = points[points.length - 1].month

  return (
    <figure className="market-chart" aria-label={CHART_TITLE[series]}>
      <figcaption>
        <strong>{CHART_TITLE[series]}</strong>
        <span className="market-chart-source">{chartSource(series, chart.as_of)}</span>
      </figcaption>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true">
        <line className="axis" x1={LEFT} x2={WIDTH - RIGHT} y1={y(0)} y2={y(0)} />
        <text className="axis-label" x={LEFT - 6} y={y(high) + 4} textAnchor="end">
          {percent(high)}
        </text>
        <text className="axis-label" x={LEFT - 6} y={y(low) + 4} textAnchor="end">
          {percent(low)}
        </text>
        <text className="axis-label" x={LEFT} y={HEIGHT - 8} textAnchor="start">
          {formatMonth(first)}
        </text>
        <text className="axis-label" x={WIDTH - RIGHT} y={HEIGHT - 8} textAnchor="end">
          {formatMonth(last)}
        </text>
        {series === 'prime' ? (
          <>
            <polyline
              className="series-line"
              points={values.map((value, i) => `${x(i)},${y(value)}`).join(' ')}
            />
            {values.map((value, i) => (
              <circle key={points[i].month} className="series-point" cx={x(i)} cy={y(value)} r={3}>
                <title>{hover(i)}</title>
              </circle>
            ))}
          </>
        ) : (
          values.map((value, i) => (
            <rect
              key={points[i].month}
              className={value < 0 ? 'series-bar negative' : 'series-bar'}
              x={x(i) - slot * 0.35}
              width={slot * 0.7}
              y={Math.min(y(value), y(0))}
              height={Math.abs(y(value) - y(0))}
            >
              <title>{hover(i)}</title>
            </rect>
          ))
        )}
      </svg>
      {/* A table ignores a height smaller than its rows, so the hidden box wraps it. */}
      <div className="visually-hidden">
        <table>
          <thead>
            <tr>
              <th>{CHART_MONTH}</th>
              <th>{CHART_VALUE[series]}</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.month}>
                <td>{formatMonth(point.month)}</td>
                <td>{`${point.value}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}
