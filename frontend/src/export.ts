/**
 * 読書記録の書き出し。
 * ブラウザ側でファイルを組み立てて保存させるので、サーバーは関わらない。
 */
import type { Book, NoteWithBook } from './api'
import { GENRE_LABELS, KIND_LABELS, STATUS_LABELS } from './api'

function download(filename: string, text: string, mime: string) {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  // 参照を解放しないとメモリに残り続ける
  URL.revokeObjectURL(url)
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

/** 本ごとに見出しを立て、その下に引用・メモを並べた Markdown */
export function exportMarkdown(books: Book[], notes: NoteWithBook[]) {
  const lines: string[] = ['# 読書記録', '']

  for (const book of books) {
    lines.push(`## ${book.title}`)
    const meta = [
      book.author,
      book.publisher,
      STATUS_LABELS[book.status],
      book.rating ? '★'.repeat(book.rating) : null,
      book.finished_on ? `読了 ${book.finished_on}` : null,
    ].filter(Boolean)
    lines.push(meta.join(' · '), '')

    const mine = notes
      .filter((note) => note.book.id === book.id)
      .sort((a, b) => (b.page ?? 0) - (a.page ?? 0))
    for (const note of mine) {
      const where = note.page ? ` (p.${note.page})` : ''
      if (note.kind === 'quote') {
        lines.push(`> ${note.text}`, `> — ${KIND_LABELS.quote}${where}`)
        if (note.memo) lines.push('', note.memo)
      } else {
        lines.push(`- ${note.text}${where}`)
      }
      lines.push('')
    }
  }
  download(`reading-notes-${today()}.md`, lines.join('\n'), 'text/markdown')
}

/** 表計算で開ける本の一覧 */
export function exportCsv(books: Book[]) {
  const header = [
    'title',
    'author',
    'publisher',
    'isbn',
    'genre',
    'status',
    'rating',
    'page',
    'total',
    'started_on',
    'finished_on',
    'notes',
  ]
  // 値にカンマ・改行・引用符が入っても壊れないよう、常に " で囲んで " を二重にする
  const escape = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`

  const rows = books.map((book) =>
    [
      book.title,
      book.author,
      book.publisher,
      book.isbn,
      GENRE_LABELS[book.genre],
      STATUS_LABELS[book.status],
      book.rating,
      book.page,
      book.total,
      book.started_on,
      book.finished_on,
      book.note_count,
    ]
      .map(escape)
      .join(','),
  )

  // 先頭の BOM は Excel で文字化けさせないためのもの
  download(
    `reading-notes-${today()}.csv`,
    `﻿${[header.join(','), ...rows].join('\r\n')}`,
    'text/csv',
  )
}
