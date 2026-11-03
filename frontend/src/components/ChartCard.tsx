import { useState, type ReactNode } from 'react'
import { t } from '../i18n'

interface TableData {
  columns: string[]
  rows: () => (string | number)[][]
}

interface Props {
  title: string
  hint?: string
  table?: TableData
  children: ReactNode
}

/** A chart with title, explanation and a table view of the same data. */
export function ChartCard({ title, hint, table, children }: Props) {
  const [open, setOpen] = useState(false)
  return (
    <section className="rounded-2xl border border-border bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <header className="mb-3">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {hint && <p className="mt-0.5 text-sm text-ink-2">{hint}</p>}
      </header>
      {children}
      {table && (
        <details className="mt-3 text-sm" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
          <summary className="cursor-pointer text-ink-2 select-none hover:text-ink">{t('showTable')}</summary>
          {open && (
            <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-border">
              <table className="w-full text-left tabular">
                <thead className="sticky top-0 bg-surface">
                  <tr>
                    {table.columns.map((column) => (
                      <th key={column} scope="col" className="border-b border-border px-3 py-2 font-medium text-ink">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows().map((row, i) => (
                    <tr key={i} className="odd:bg-wash/50">
                      {row.map((cell, j) => (
                        <td key={j} className="px-3 py-1.5 whitespace-nowrap text-ink-2">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </details>
      )}
    </section>
  )
}
