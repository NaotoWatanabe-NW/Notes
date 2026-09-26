/**
 * 本棚の絞り込みと、選んだ本の見え方。
 *
 * 絞り込みが効いていると、追加したばかりの本が一覧に出てこないことがある
 * （読了タブを見ているときに積読の本を足した、など）。「追加したのに
 * 反映されない」と見えてしまうので、**その本を隠している絞り込みだけ**を外す。
 * 関係のない絞り込みは触らない。
 */
import type { BookStatus } from './api'

export type LibraryFilters = {
  /** 状態での絞り込み。null は「すべて」 */
  status: BookStatus | null
  /** タグでの絞り込み。null は絞り込みなし */
  tag: string | null
}

type BookLike = { status: BookStatus; tags: string[] }

/** その本が今の絞り込みで一覧に出るか */
export function isVisible(book: BookLike, filters: LibraryFilters): boolean {
  if (filters.status !== null && book.status !== filters.status) return false
  if (filters.tag !== null && !book.tags.includes(filters.tag)) return false
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
  }
}
