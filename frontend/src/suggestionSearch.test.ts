import { describe, expect, it } from 'vitest'
import type { SuggestionWithBook } from './api'
import { groupBySource, markShelved, matchesKeyword } from './suggestionSearch'

function item(fields: Partial<SuggestionWithBook> = {}): SuggestionWithBook {
  return {
    id: 1,
    isbn: '9784622089643',
    title: '数の発明',
    author: 'ケイレブ・エヴェレット',
    cover_url: null,
    basis: 'tag',
    distance: 'far',
    reason: 'ピダハンの「数のない言語」から、数量認知という認知科学の問いへとつながります。',
    added_book_id: null,
    book: { id: 19, title: 'ピダハン', author: 'エヴェレット' },
    ...fields,
  }
}

describe('matchesKeyword', () => {
  it('書名に含まれる語で見つかる', () => {
    expect(matchesKeyword(item(), '発明')).toBe(true)
  })

  it('紹介文（理由）に含まれる語で見つかる', () => {
    expect(matchesKeyword(item(), '認知科学')).toBe(true)
  })

  it('著者名やどの本の候補かは対象にしない', () => {
    // 絞り込みは書名と紹介文だけ、と決めた
    expect(matchesKeyword(item({ reason: '理由' }), 'エヴェレット')).toBe(false)
    expect(matchesKeyword(item({ reason: '理由' }), 'ピダハン')).toBe(false)
  })

  it('空白で区切った語は全部含むものだけ残る', () => {
    expect(matchesKeyword(item(), '数 認知')).toBe(true)
    expect(matchesKeyword(item(), '数 地政学')).toBe(false)
  })

  it('全角の空白でも語を区切れる', () => {
    expect(matchesKeyword(item(), '数　認知')).toBe(true)
  })

  it('全角半角・大文字小文字・ひらがなカタカナの違いは問わない', () => {
    expect(matchesKeyword(item({ title: 'AI駆動開発の教科書' }), 'ａｉ')).toBe(true)
    expect(matchesKeyword(item({ title: 'ゲーム理論・入門' }), 'げーむ')).toBe(true)
  })

  it('語が空なら全部残る', () => {
    expect(matchesKeyword(item(), '')).toBe(true)
    expect(matchesKeyword(item(), '   ')).toBe(true)
  })
})

describe('groupBySource', () => {
  it('どの本の候補かでまとめ、受け取った順を保つ', () => {
    const groups = groupBySource([
      item({ id: 1, book: { id: 19, title: 'ピダハン', author: null } }),
      item({ id: 2, book: { id: 39, title: '科学革命の構造', author: null } }),
      item({ id: 3, book: { id: 19, title: 'ピダハン', author: null } }),
    ])
    expect(groups.map((group) => group.book.title)).toEqual(['ピダハン', '科学革命の構造'])
    expect(groups[0].items.map((entry) => entry.id)).toEqual([1, 3])
  })

  it('候補がなければまとまりもない', () => {
    expect(groupBySource([])).toEqual([])
  })
})

describe('markShelved', () => {
  it('本棚にある本の候補は、押していなくても追加済みにする', () => {
    const [marked] = markShelved([item({ isbn: '9784622089643' })], [
      { id: 200, isbn: '9784622089643' },
    ])
    expect(marked.added_book_id).toBe(200)
  })

  it('本棚にない本の候補はそのまま', () => {
    const [kept] = markShelved([item()], [{ id: 200, isbn: '9784000000000' }])
    expect(kept.added_book_id).toBeNull()
  })

  it('ISBN が分からない候補は本棚の本と取り違えない', () => {
    const [kept] = markShelved([item({ isbn: null })], [{ id: 200, isbn: null }])
    expect(kept.added_book_id).toBeNull()
  })
})
