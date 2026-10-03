import { describe, expect, it } from 'vitest'
import { pageFromPercent } from './progress'

describe('pageFromPercent', () => {
  it('100％なら最後のページを返す', () => {
    expect(pageFromPercent(100, 300)).toBe(300)
  })

  it('0％なら0ページを返す', () => {
    expect(pageFromPercent(0, 300)).toBe(0)
  })

  it('途中の％はそのページ数に直す', () => {
    expect(pageFromPercent(41, 300)).toBe(123)
    expect(pageFromPercent(50, 320)).toBe(160)
  })

  it('99％は短い本でも最後のページに届かない', () => {
    // 四捨五入だと 10ページの本の 99％ が 10 になり、
    // サーバーの「最後まで読んだら読了」で勝手に読了になってしまう
    expect(pageFromPercent(99, 10)).toBe(9)
    expect(pageFromPercent(96, 25)).toBe(24)
  })

  it('100％を超える値でも最後のページを超えない', () => {
    expect(pageFromPercent(120, 300)).toBe(300)
  })

  it('負の％は0ページとして扱う', () => {
    expect(pageFromPercent(-5, 300)).toBe(0)
  })
})
