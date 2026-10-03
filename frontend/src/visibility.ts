/**
 * 本棚の絞り込みと、選んだ本の見え方。
 *
 * 絞り込みは 状態・カテゴリ・タグ の3つで、すべて同時に効く（デザイン 8b）。
 * 絞り込みが効いていると、追加したばかりの本が一覧に出てこないことがある
 * （読了タブを見ているときに積読の本を足した、など）。「追加したのに
 * 反映されない」と見えてしまうので、**その本を隠している絞り込みだけ**を外す。
 * 関係のない絞り込みは触らない。
 */
import type { BookStatus, Genre } from './api'

export type LibraryFilters = {
  /** 状態での絞り込み。null は「すべて」 */
  status: BookStatus | null
  /** タグでの絞り込み。null は絞り込みなし */
  tag: string | null
  /** カテゴリでの絞り込み。null は「すべて」 */
  genre: Genre | null
}

type BookLike = { status: BookStatus; tags: string[]; genre: Genre }

/** その本が今の絞り込みで一覧に出るか */
export function isVisible(book: BookLike, filters: LibraryFilters): boolean {
  if (filters.status !== null && book.status !== filters.status) return false
  if (filters.tag !== null && !book.tags.includes(filters.tag)) return false
  if (filters.genre !== null && book.genre !== filters.genre) return false
  return true
}

/**
 * その本が見えるようになる絞り込みを返す。
 * もともと見えているなら、渡された絞り込みをそのまま返す。
 */
export function filtersRevealing(
  book: BookLike,
  filters: LibraryFilters,
): LibraryFilters {
  return {
    status:
      filters.status !== null && book.status !== filters.status ? null : filters.status,
    tag:
      filters.tag !== null && !book.tags.includes(filters.tag) ? null : filters.tag,
    genre:
      filters.genre !== null && book.genre !== filters.genre ? null : filters.genre,
  }
}

/**
 * 本棚の「タグ」行に出すタグ。よく使う順に limit 個（デザインは8つ）。
 * 同じ数なら名前順。選んでいるタグが圏外なら最後に足す（本の詳細のタグから
 * 絞り込んだとき、何で絞っているかが見えて、押して外せるように）。
 */
export function topTags(
  books: { tags: string[] }[],
  selected: string | null,
  limit = 8,
): string[] {
  const counts = new Map<string, number>()
  for (const book of books) {
    for (const tag of book.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1)
  }
  const top = [...counts.keys()]
    .sort((a, b) => (counts.get(b) ?? 0) - (counts.get(a) ?? 0) || a.localeCompare(b, 'ja'))
    .slice(0, limit)
  if (selected !== null && !top.includes(selected)) top.push(selected)
  return top
}
