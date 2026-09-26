import { describe, expect, it } from 'vitest'
import { filtersRevealing, isVisible } from './visibility'

const 積読 = { status: 'unread' as const, tags: ['技術書'] }
const 読了 = { status: 'finished' as const, tags: ['小説'] }
const タグなし = { status: 'unread' as const, tags: [] }

describe('isVisible', () => {
  it('絞り込みが無ければ出る', () => {
    expect(isVisible(積読, { status: null, tag: null })).toBe(true)
  })

  it('状態が合えば出る', () => {
    expect(isVisible(積読, { status: 'unread', tag: null })).toBe(true)
  })

  it('状態が違えば出ない', () => {
    expect(isVisible(積読, { status: 'finished', tag: null })).toBe(false)
  })

  it('タグが合えば出る', () => {
    expect(isVisible(積読, { status: null, tag: '技術書' })).toBe(true)
  })

  it('タグが無ければ出ない', () => {
    expect(isVisible(タグなし, { status: null, tag: '技術書' })).toBe(false)
  })

  it('状態が合ってもタグが合わなければ出ない', () => {
    expect(isVisible(積読, { status: 'unread', tag: '小説' })).toBe(false)
  })
})

describe('filtersRevealing（隠している絞り込みだけ外す）', () => {
  it('読了タブで積読の本を足したら、状態の絞り込みを外す', () => {
    // 「追加したのに一覧に出てこない」を防ぐ
    expect(filtersRevealing(積読, { status: 'finished', tag: null })).toEqual({
      status: null,
      tag: null,
    })
  })

  it('もともと見えているなら絞り込みを変えない', () => {
    const filters = { status: 'unread' as const, tag: '技術書' }
    expect(filtersRevealing(積読, filters)).toEqual(filters)
  })

  it('タグが合わないときはタグの絞り込みだけ外す', () => {
    // 状態は合っているので、そちらは残す
    expect(filtersRevealing(積読, { status: 'unread', tag: '小説' })).toEqual({
      status: 'unread',
      tag: null,
    })
  })

  it('状態が合わないときは状態の絞り込みだけ外す', () => {
    expect(filtersRevealing(読了, { status: 'unread', tag: '小説' })).toEqual({
      status: null,
      tag: '小説',
    })
  })

  it('両方合わなければ両方外す', () => {
    expect(filtersRevealing(タグなし, { status: 'finished', tag: '技術書' })).toEqual({
      status: null,
      tag: null,
    })
  })

  it('外したあとは必ずその本が見えるようになる', () => {
    const cases = [積読, 読了, タグなし]
    const filters = [
      { status: 'finished' as const, tag: '技術書' },
      { status: 'unread' as const, tag: null },
      { status: null, tag: '小説' },
    ]
    for (const book of cases) {
      for (const f of filters) {
        expect(isVisible(book, filtersRevealing(book, f))).toBe(true)
      }
    }
  })
})
