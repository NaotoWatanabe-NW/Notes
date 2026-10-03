/**
 * おすすめ一覧（デザイン J）の見せ方の小道具。PC版・モバイル版で共有する。
 */
import type { Recommendation, RecommendationSource } from './api'

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
