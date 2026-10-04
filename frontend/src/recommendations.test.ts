import { describe, expect, it } from 'vitest'
import type { RecommendationSource } from './api'
import { fromBooks, metaLine, sourceLabel } from './recommendations'

describe('sourceLabel', () => {
  it('本の候補は「『書名』を読んだあとに」', () => {
    expect(sourceLabel({ kind: 'book', label: 'ピダハン', book_id: 19, basis: 'tag', reason: '' })).toBe(
      '『ピダハン』を読んだあとに',
    )
  })

  it('キーワードの候補は「キーワード「…」から」', () => {
    expect(sourceLabel({ kind: 'topic', label: '統計', book_id: null, basis: null, reason: '' })).toBe(
      'キーワード「統計」から',
    )
  })
})

describe('metaLine', () => {
  it('著者・出版社・ページ数を「 · 」でつなぐ', () => {
    expect(metaLine({ author: '小川洋子', publisher: '新潮文庫', total: 291 })).toBe(
      '小川洋子 · 新潮文庫 · 291ページ',
    )
  })

  it('分からない項目は省く', () => {
    expect(metaLine({ author: '小川洋子', publisher: null, total: null })).toBe('小川洋子')
    expect(metaLine({ author: null, publisher: '新潮文庫', total: 291 })).toBe(
      '新潮文庫 · 291ページ',
    )
  })
})

describe('fromBooks（本棚のこの本から）', () => {
  const shelf = [
    { id: 1, title: 'こころ', status: 'finished' as const, rating: 5, note_count: 0, tags: ['近代文学'] },
    { id: 2, title: '暇と退屈の倫理学', status: 'reading' as const, rating: null, note_count: 6, tags: ['哲学'] },
    { id: 3, title: 'サピエンス全史', status: 'unread' as const, rating: null, note_count: 0, tags: ['歴史', '生物学', '人類'] },
    { id: 4, title: 'タグなし', status: 'unread' as const, rating: null, note_count: 0, tags: [] },
  ]
  const source = (fields: Partial<RecommendationSource>): RecommendationSource => ({
    kind: 'book',
    label: '',
    book_id: null,
    basis: 'tag',
    reason: '',
    ...fields,
  })

  it('状態と、なぜ選んだかに合わせた結び付きを出す', () => {
    const got = fromBooks(
      {
        sources: [
          source({ book_id: 1, basis: 'rating' }),
          source({ book_id: 2, basis: 'note' }),
          source({ book_id: 3, basis: 'tag' }),
          source({ book_id: 4, basis: 'tag' }),
        ],
      },
      shelf,
    )
    expect(got.map((entry) => entry.via)).toEqual([
      '読了 · ★5をつけた本',
      '読書中 · 引用・メモ 6件',
      '積読 · #歴史 #生物学',
      '積読 · 分野から',
    ])
  })

  it('キーワードの候補は手がかりにした本を、キーワードと一緒に出す', () => {
    const got = fromBooks(
      { sources: [source({ kind: 'topic', label: '統計', book_id: 2, basis: null })] },
      shelf,
    )
    expect(got).toEqual([{ book: shelf[1], via: '読書中 · キーワード「統計」の手がかり' }])
  })

  it('元の本が本棚に無いものと、元の本が無いものは出さない', () => {
    const got = fromBooks(
      { sources: [source({ book_id: 99 }), source({ kind: 'topic', book_id: null, basis: null })] },
      shelf,
    )
    expect(got).toEqual([])
  })

  it('同じ本は1回だけ出し、本の候補を優先する', () => {
    const got = fromBooks(
      {
        sources: [
          source({ kind: 'topic', label: '統計', book_id: 1, basis: null }),
          source({ book_id: 1, basis: 'rating' }),
        ],
      },
      shelf,
    )
    expect(got.map((entry) => entry.via)).toEqual(['読了 · ★5をつけた本'])
  })
})
