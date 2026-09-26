import type { BookStatus } from './api'

/** 左のレールで切り替える画面 */
export type View = 'library' | 'notes' | 'review' | 'settings'

/** 本棚の絞り込み。null は「すべて」 */
export type LibraryFilter = BookStatus | null

/** メモ・引用の絞り込み。null は「すべて」 */
export type NoteFilter = 'quote' | 'memo' | null
