/**
 * おすすめ一覧（デザイン J）の見せ方の小道具。PC版・モバイル版で共有する。
 */
import type { Book, Recommendation, RecommendationSource } from './api'
import { STATUS_LABELS } from './api'

/** どこから選ばれたか。「『ピダハン』を読んだあとに」「キーワード「統計」から」 */
export function sourceLabel(source: RecommendationSource): string {
  return source.kind === 'book'
    ? `『${source.label}』を読んだあとに`
    : `キーワード「${source.label}」から`
}

/** 詳細のメタ行。「小川洋子 · 新潮文庫 · 291ページ」。分からない項目は省く */
export function metaLine(item: Pick<Recommendation, 'author' | 'publisher' | 'total'>): string {
  return [item.author, item.publisher, item.total ? `${item.total}ページ` : null]
    .filter(Boolean)
    .join(' · ')
}

type ShelfBook = Pick<Book, 'id' | 'title' | 'status' | 'rating' | 'note_count' | 'tags'>

/** 元の本との結び付き（デザインの「★5をつけた小説」「#哲学 · 引用 6件」にあたる） */
function viaText(source: RecommendationSource, book: ShelfBook): string {
  if (source.kind === 'topic') return `キーワード「${source.label}」の手がかり`
  if (source.basis === 'rating' && book.rating) return `★${book.rating}をつけた本`
  if (source.basis === 'note' && book.note_count > 0) return `引用・メモ ${book.note_count}件`
  if (book.tags.length > 0) {
    return book.tags
      .slice(0, 2)
      .map((tag) => `#${tag}`)
      .join(' ')
  }
  return '分野から'
}

export type FromBook<B extends ShelfBook> = { book: B; via: string }

/**
 * 「本棚のこの本から」に出す本（デザイン J）。行の2行目は「状態 · 結び付き」。
 * 元の本が本棚から消えていれば出さない。同じ本は1回だけ（本の候補を優先）。
 */
export function fromBooks<B extends ShelfBook>(
  item: Pick<Recommendation, 'sources'>,
  books: B[],
): FromBook<B>[] {
  const ordered = [
    ...item.sources.filter((source) => source.kind === 'book'),
    ...item.sources.filter((source) => source.kind === 'topic'),
  ]
  const result: FromBook<B>[] = []
  for (const source of ordered) {
    const book = books.find((candidate) => candidate.id === source.book_id)
    if (!book || result.some((entry) => entry.book.id === book.id)) continue
    result.push({ book, via: `${STATUS_LABELS[book.status]} · ${viaText(source, book)}` })
  }
  return result
}
