/**
 * バックエンド (/api/...) とのやり取りをここにまとめる。
 * 画面側のコンポーネントは fetch を直接書かず、この関数たちを呼ぶ。
 */

export type BookStatus = 'unread' | 'reading' | 'finished'
export type Recommend = 'strong' | 'some' | 'self'
export type NoteKind = 'quote' | 'memo'
export type BookSort = 'recent' | 'title' | 'progress'
export type QuoteStyle = 'italic' | 'plain'
/** 本のカテゴリ。細かい分野はタグで持つ（`category` は国会図書館の件名で別物） */
export type Genre = 'novel' | 'business' | 'essay' | 'academic' | 'magazine' | 'other'

export const STATUS_LABELS: Record<BookStatus, string> = {
  reading: '読書中',
  finished: '読了',
  unread: '積読',
}

/** 並びは画面に出す順 */
export const GENRE_LABELS: Record<Genre, string> = {
  novel: '小説',
  business: 'ビジネス・実用',
  essay: 'エッセイ',
  academic: '学術',
  magazine: '雑誌',
  other: 'その他',
}

export const KIND_LABELS: Record<NoteKind, string> = {
  quote: '引用',
  memo: 'メモ',
}

export const RECOMMEND_LABELS: Record<Recommend, string> = {
  strong: '人にすすめたい',
  some: '人を選ぶ',
  self: '自分用',
}

export const SORT_LABELS: Record<BookSort, string> = {
  recent: '追加順',
  title: '書名',
  progress: '進捗',
}

export type Reading = { id: number; finished_on: string }

export type Book = {
  id: number
  isbn: string | null
  title: string
  author: string | null
  publisher: string | null
  category: string | null
  /** カテゴリ。決めていない本は「その他」 */
  genre: Genre
  cover_url: string | null
  status: BookStatus
  rating: number | null
  recommend: Recommend | null
  page: number
  total: number | null
  started_on: string | null
  finished_on: string | null
  progress: number | null
  note_count: number
  /** 読み終えた回数。再読するたびに増える */
  read_count: number
  has_report: boolean
  tags: string[]
  created_at: string
  updated_at: string
}

/** 本の詳細。一覧では省いているレポート本文と読了の履歴まで入っている */
export type BookDetail = Book & {
  report_md: string | null
  readings: Reading[]
}

export type BookCreate = {
  title: string
  isbn?: string | null
  author?: string | null
  publisher?: string | null
  category?: string | null
  genre?: Genre
  cover_url?: string | null
  status?: BookStatus
  total?: number | null
  tags?: string[]
}

export type BookUpdate = Partial<
  BookCreate & {
    rating: number | null
    recommend: Recommend | null
    page: number
    started_on: string | null
    finished_on: string | null
    report_md: string | null
  }
>

export type Note = {
  id: number
  book_id: number
  kind: NoteKind
  page: number | null
  text: string
  memo: string | null
  created_at: string
  updated_at: string
}

/** 「メモ・引用」ビュー用。出典の本が付いてくる */
export type NoteWithBook = Note & {
  book: { id: number; title: string; author: string | null; cover_url: string | null }
}

export type NoteCreate = {
  kind: NoteKind
  text: string
  page?: number | null
  memo?: string | null
}
export type NoteUpdate = Partial<NoteCreate>

export type Settings = {
  yearly_goal: number
  sort: BookSort
  quote_style: QuoteStyle
}
export type SettingsUpdate = Partial<Settings>

/** ISBN 検索の結果。DBには保存されていない、フォームを埋めるためだけの情報 */
export type BookInfo = {
  isbn: string
  title: string
  author: string | null
  publisher: string | null
  total: number | null
  category: string | null
  cover_url: string | null
  source: string
}

export type ReviewPeriod = {
  period: string
  label: string
  sub: string
  count: number
}
export type ReviewBar = { label: string; value: number; current: boolean }
export type ReviewBook = {
  id: number
  title: string
  author: string | null
  cover_url: string | null
}
export type Review = {
  label: string
  finished_count: number
  yearly_goal: number | null
  remaining_to_goal: number | null
  pages: number
  note_count: number
  top_category: string | null
  bars: ReviewBar[]
  books: ReviewBook[]
  top_quote: { text: string; book_title: string; page: number | null } | null
}

/** API がエラーを返したときに投げる例外。画面にそのまま出せる message を持つ */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * FastAPI のエラー本文から、画面に出せる1行のメッセージを取り出す。
 * 422 のときは detail が配列（項目ごとの検証エラー）で返ってくる。
 */
function extractMessage(status: number, body: unknown): string {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (typeof item !== 'object' || item === null) return null
          const { loc, msg } = item as { loc?: unknown[]; msg?: string }
          const field = Array.isArray(loc) ? loc[loc.length - 1] : undefined
          return field ? `${field}: ${msg}` : msg
        })
        .filter(Boolean)
      if (messages.length > 0) return messages.join(' / ')
    }
  }
  return `エラーが発生しました (HTTP ${status})`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })

  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      // 本文が JSON でないこともある。その場合は status だけで判断する
    }
    throw new ApiError(response.status, extractMessage(response.status, body))
  }

  // 204 No Content には本文がない
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// ---------------------------------------------------------------- 本

export function listBooks(params?: {
  status?: BookStatus
  sort?: BookSort
  tag?: string
}) {
  const query = new URLSearchParams()
  if (params?.status) query.set('status', params.status)
  if (params?.sort) query.set('sort', params.sort)
  if (params?.tag) query.set('tag', params.tag)
  const suffix = query.toString() ? `?${query}` : ''
  return request<Book[]>(`/api/books${suffix}`)
}

export const getBook = (id: number) => request<BookDetail>(`/api/books/${id}`)

export const createBook = (payload: BookCreate) =>
  request<BookDetail>('/api/books', { method: 'POST', body: JSON.stringify(payload) })

export const updateBook = (id: number, payload: BookUpdate) =>
  request<BookDetail>(`/api/books/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const deleteBook = (id: number) =>
  request<void>(`/api/books/${id}`, { method: 'DELETE' })

/**
 * 表紙の画像を入れ替える。
 * 国会図書館に書影が無い本のために、手で入れられるようにしてある。
 */
export async function setCover(bookId: number, file: File): Promise<BookDetail> {
  const body = new FormData()
  body.append('file', file)
  // FormData のときは Content-Type をこちらで決めない（境界文字列が要るため）
  const response = await fetch(`/api/books/${bookId}/cover`, { method: 'PUT', body })
  if (!response.ok) {
    let payload: unknown = null
    try {
      payload = await response.json()
    } catch {
      // 本文が JSON でないこともある
    }
    throw new ApiError(response.status, extractMessage(response.status, payload))
  }
  return (await response.json()) as BookDetail
}

/** 自分で入れた表紙を外す */
export const deleteCover = (bookId: number) =>
  request<BookDetail>(`/api/books/${bookId}/cover`, { method: 'DELETE' })

// ---------------------------------------------------------------- ノート

export const listBookNotes = (bookId: number) =>
  request<Note[]>(`/api/books/${bookId}/notes`)

export const listNotes = (kind?: NoteKind) =>
  request<NoteWithBook[]>(`/api/notes${kind ? `?kind=${kind}` : ''}`)

export const createNote = (bookId: number, payload: NoteCreate) =>
  request<Note>(`/api/books/${bookId}/notes`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateNote = (noteId: number, payload: NoteUpdate) =>
  request<Note>(`/api/notes/${noteId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const deleteNote = (noteId: number) =>
  request<void>(`/api/notes/${noteId}`, { method: 'DELETE' })

// ---------------------------------------------------------------- そのほか

export const getSettings = () => request<Settings>('/api/settings')

export const updateSettings = (payload: SettingsUpdate) =>
  request<Settings>('/api/settings', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const listPeriods = () => request<ReviewPeriod[]>('/api/reviews')

export const getReview = (period: string) => request<Review>(`/api/reviews/${period}`)

/** ISBN から本の情報を調べる。見つからないときは 404 → ApiError になる */
export const lookupIsbn = (isbn: string) =>
  request<BookInfo>(`/api/isbn/${encodeURIComponent(isbn)}`)

/** 書名で外部カタログを探す。⌘K の「本を追加」で使う */
export const searchCatalog = (query: string, limit = 4) =>
  request<BookInfo[]>(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}`)

// ---------------------------------------------------------------- タグ

export type TagCount = { name: string; count: number }

export const listTags = () => request<TagCount[]>('/api/tags')

// ---------------------------------------------------------------- 次に読む本

/** なぜその本を出したか */
export type Basis = 'note' | 'rating' | 'tag'
/** 読んできた本との距離 */
export type Distance = 'near' | 'far' | 'both'

export const BASIS_LABELS: Record<Basis, string> = {
  note: '引用・メモから',
  rating: '評価から',
  tag: '分野から',
}

export const DISTANCE_LABELS: Record<Distance, string> = {
  near: '近い本',
  far: '少し離れた本',
  both: '両方',
}

export type Suggestion = {
  id: number
  isbn: string | null
  title: string
  author: string | null
  cover_url: string | null
  basis: Basis
  distance: Exclude<Distance, 'both'>
  reason: string
  /** 積読に追加済みなら、その本の id */
  added_book_id: number | null
}

/** 候補を設定するときに送る形（id などは要らない） */
export type SuggestionWrite = Omit<Suggestion, 'id' | 'added_book_id'>

export type SuggestionSet = {
  book_id: number
  book_title: string
  days: number | null
  note_count: number
  /** そもそも候補を設定してあるか。false なら「まだ検索していません」 */
  configured: boolean
  suggestions: Suggestion[]
  summary: string
  has_more: boolean
}

export function getSuggestions(
  bookId: number,
  params: { basis: Basis[]; distance: Distance; page: number; perPage?: number },
) {
  const query = new URLSearchParams({
    basis: params.basis.join(','),
    distance: params.distance,
    page: String(params.page),
  })
  // 1ページの冊数。読了ダイアログは既定（3冊）のまま、
  // 本の詳細画面は設定してある候補を全部出したいので指定する
  if (params.perPage !== undefined) query.set('per_page', String(params.perPage))
  return request<SuggestionSet>(`/api/books/${bookId}/suggestions?${query}`)
}

/** その本の「次に読む本」をまとめて入れ替える */
export const setSuggestions = (bookId: number, items: SuggestionWrite[]) =>
  request<Suggestion[]>(`/api/books/${bookId}/suggestions`, {
    method: 'PUT',
    body: JSON.stringify(items),
  })

/** 候補を積読として本棚に追加する */
export const addSuggestionToShelf = (suggestionId: number) =>
  request<BookDetail>(`/api/suggestions/${suggestionId}/add`, { method: 'POST' })

/** おすすめ一覧で候補に添える「どの本の候補か」（その本を読み終えたときに出す） */
export type SuggestionSource = { id: number; title: string; author: string | null }

export type SuggestionWithBook = Suggestion & { book: SuggestionSource }

/** 設定してある「次に読む本」を全部、どの本の候補かを添えて取る（おすすめ一覧） */
export const listAllSuggestions = () => request<SuggestionWithBook[]>('/api/suggestions')

/** 「興味なし」。以後のおすすめから外す */
export const dismissSuggestion = (isbn: string) =>
  request<void>(`/api/suggestions/dismiss?isbn=${encodeURIComponent(isbn)}`, {
    method: 'POST',
  })
