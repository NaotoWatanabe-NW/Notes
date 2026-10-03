import { describe, expect, it } from 'vitest'
import { metaLine, sourceLabel } from './recommendations'

describe('sourceLabel', () => {
  it('本の候補は「『書名』を読んだあとに」', () => {
    expect(sourceLabel({ kind: 'book', label: 'ピダハン', book_id: 19, reason: '' })).toBe(
      '『ピダハン』を読んだあとに',
    )
  })

  it('キーワードの候補は「キーワード「…」から」', () => {
    expect(sourceLabel({ kind: 'topic', label: '統計', book_id: null, reason: '' })).toBe(
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
