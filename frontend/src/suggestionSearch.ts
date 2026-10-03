/**
 * おすすめ一覧の絞り込みとまとめ方（PC版・モバイル版で共有）。
 *
 * 絞り込みは**書名と紹介文（理由の一言）だけ**を見るキーワード検索。
 * 著者名や、どの本の候補かは対象にしない（そう決めた）。
 * 外部のサービスにも Claude にも問い合わせず、取ってきた一覧の中だけで探す。
 */
import type { SuggestionSource, SuggestionWithBook } from './api'

/** 表記のゆれをそろえる（全角/半角・大文字/小文字・ひらがな/カタカナ） */
function fold(text: string): string {
  return text
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[ぁ-ゖ]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) + 0x60))
}

/** 空白（全角も）で区切った語を、書名と紹介文のどこかに全部含むか */
export function matchesKeyword(
  item: Pick<SuggestionWithBook, 'title' | 'reason'>,
  query: string,
): boolean {
  const terms = fold(query).split(/\s+/).filter(Boolean)
  if (terms.length === 0) return true
  const haystack = fold(`${item.title}\n${item.reason}`)
  return terms.every((term) => haystack.includes(term))
}

export type SourceGroup = { book: SuggestionSource; items: SuggestionWithBook[] }

/** どの本の候補かでまとめる。並びは受け取った順（本ごと・設定した順）のまま */
export function groupBySource(items: SuggestionWithBook[]): SourceGroup[] {
  const groups = new Map<number, SourceGroup>()
  for (const item of items) {
    const found = groups.get(item.book.id)
    if (found) {
      found.items.push(item)
    } else {
      groups.set(item.book.id, { book: item.book, items: [item] })
    }
  }
  return [...groups.values()]
}

/**
 * 本棚にある本の候補を「積読に追加済み」にする。
 *
 * 同じ本が何冊もの本の候補に出る（「予想どおりに不合理」は6冊ぶん）。
 * サーバーは押した候補にしか印を付けないので、1か所で足したら
 * ほかの候補にも印を出す。
 */
export function markShelved(
  items: SuggestionWithBook[],
  shelf: { id: number; isbn: string | null }[],
): SuggestionWithBook[] {
  const idByIsbn = new Map<string, number>()
  for (const book of shelf) {
    if (book.isbn) idByIsbn.set(book.isbn, book.id)
  }
  return items.map((item) => {
    const shelvedId = item.isbn ? idByIsbn.get(item.isbn) : undefined
    return item.added_book_id === null && shelvedId !== undefined
      ? { ...item, added_book_id: shelvedId }
      : item
  })
}
