import { describe, expect, it } from 'vitest'
import type { LibraryFilters } from './visibility'
import { filtersRevealing, isVisible, topTags } from './visibility'

const 積読 = { status: 'unread' as const, tags: ['技術書'], genre: 'business' as const }
const 読了 = { status: 'finished' as const, tags: ['小説'], genre: 'novel' as const }
const タグなし = { status: 'unread' as const, tags: [], genre: 'other' as const }

/** 指定しなかった絞り込みは「すべて」 */
function f(filters: Partial<LibraryFilters>): LibraryFilters {
  return { status: null, tag: null, genre: null, ...filters }
}

describe('isVisible', () => {
  it('絞り込みが無ければ出る', () => {
    expect(isVisible(積読, f({}))).toBe(true)
  })

  it('状態が合えば出る', () => {
    expect(isVisible(積読, f({ status: 'unread' }))).toBe(true)
  })

  it('状態が違えば出ない', () => {
    expect(isVisible(積読, f({ status: 'finished' }))).toBe(false)
  })

  it('タグが合えば出る', () => {
    expect(isVisible(積読, f({ tag: '技術書' }))).toBe(true)
  })

  it('タグが無ければ出ない', () => {
    expect(isVisible(タグなし, f({ tag: '技術書' }))).toBe(false)
  })

  it('状態が合ってもタグが合わなければ出ない', () => {
    expect(isVisible(積読, f({ status: 'unread', tag: '小説' }))).toBe(false)
  })

  it('カテゴリが合えば出て、違えば出ない', () => {
    expect(isVisible(読了, f({ genre: 'novel' }))).toBe(true)
    expect(isVisible(積読, f({ genre: 'novel' }))).toBe(false)
  })

  it('状態・カテゴリ・タグはすべて同時に効く', () => {
    expect(isVisible(積読, f({ status: 'unread', tag: '技術書', genre: 'business' }))).toBe(true)
    expect(isVisible(積読, f({ status: 'unread', tag: '技術書', genre: 'academic' }))).toBe(false)
  })
})

describe('filtersRevealing（隠している絞り込みだけ外す）', () => {
  it('読了タブで積読の本を足したら、状態の絞り込みを外す', () => {
    // 「追加したのに一覧に出てこない」を防ぐ
    expect(filtersRevealing(積読, f({ status: 'finished' }))).toEqual(f({}))
  })

  it('もともと見えているなら絞り込みを変えない', () => {
    const filters = f({ status: 'unread', tag: '技術書', genre: 'business' })
    expect(filtersRevealing(積読, filters)).toEqual(filters)
  })

  it('タグが合わないときはタグの絞り込みだけ外す', () => {
    // 状態は合っているので、そちらは残す
    expect(filtersRevealing(積読, f({ status: 'unread', tag: '小説' }))).toEqual(
      f({ status: 'unread' }),
    )
  })

  it('状態が合わないときは状態の絞り込みだけ外す', () => {
    expect(filtersRevealing(読了, f({ status: 'unread', tag: '小説' }))).toEqual(
      f({ tag: '小説' }),
    )
  })

  it('カテゴリが合わないときはカテゴリの絞り込みだけ外す', () => {
    // 小説を見ているときにビジネス書を足した
    expect(filtersRevealing(積読, f({ status: 'unread', genre: 'novel' }))).toEqual(
      f({ status: 'unread' }),
    )
  })

  it('全部合わなければ全部外す', () => {
    expect(
      filtersRevealing(タグなし, f({ status: 'finished', tag: '技術書', genre: 'novel' })),
    ).toEqual(f({}))
  })

  it('外したあとは必ずその本が見えるようになる', () => {
    const cases = [積読, 読了, タグなし]
    const filters = [
      f({ status: 'finished', tag: '技術書' }),
      f({ status: 'unread' }),
      f({ tag: '小説' }),
      f({ genre: 'novel' }),
      f({ genre: 'other' }),
      f({ status: 'unread', genre: 'business' }),
    ]
    for (const book of cases) {
      for (const filter of filters) {
        expect(isVisible(book, filtersRevealing(book, filter))).toBe(true)
      }
    }
  })
})

describe('topTags（本棚の「タグ」行）', () => {
  const books = [
    { tags: ['歴史', '哲学'] },
    { tags: ['歴史'] },
    { tags: ['哲学', '数学'] },
    { tags: ['歴史', '宗教'] },
  ]

  it('よく使う順に並べ、同じ数なら名前順にする', () => {
    expect(topTags(books, null)).toEqual(['歴史', '哲学', '宗教', '数学'])
  })

  it('決めた数で切る', () => {
    expect(topTags(books, null, 2)).toEqual(['歴史', '哲学'])
  })

  it('選んでいるタグが圏外なら最後に足す', () => {
    expect(topTags(books, '数学', 2)).toEqual(['歴史', '哲学', '数学'])
  })

  it('選んでいるタグが圏内なら重ねない', () => {
    expect(topTags(books, '哲学', 2)).toEqual(['歴史', '哲学'])
  })
})
