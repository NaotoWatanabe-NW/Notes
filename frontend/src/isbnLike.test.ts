import { describe, expect, it } from 'vitest'
import { looksLikeIsbn } from './isbnLike'

describe('looksLikeIsbn', () => {
  it('13桁の数字はISBNらしい', () => {
    expect(looksLikeIsbn('9784274226298')).toBe(true)
  })

  it('ハイフン付きでもISBNらしい', () => {
    expect(looksLikeIsbn('978-4-274-22629-8')).toBe(true)
  })

  it('空白付きでもISBNらしい', () => {
    expect(looksLikeIsbn('978 4 274 22629 8')).toBe(true)
  })

  it('10桁の数字はISBNらしい', () => {
    expect(looksLikeIsbn('4274226298')).toBe(true)
  })

  it('末尾がXの10桁もISBNらしい', () => {
    expect(looksLikeIsbn('020161622X')).toBe(true)
  })

  it('書名はISBNではない', () => {
    expect(looksLikeIsbn('達人プログラマー')).toBe(false)
  })

  it('桁数が足りない数字はISBNではない', () => {
    expect(looksLikeIsbn('12345')).toBe(false)
  })

  it('桁数が多すぎる数字はISBNではない', () => {
    expect(looksLikeIsbn('97842742262981')).toBe(false)
  })

  it('数字と文字が混ざったものはISBNではない', () => {
    expect(looksLikeIsbn('978abc4274226')).toBe(false)
  })

  it('空文字はISBNではない', () => {
    expect(looksLikeIsbn('')).toBe(false)
  })
})
