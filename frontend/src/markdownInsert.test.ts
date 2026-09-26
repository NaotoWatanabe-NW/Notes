import { describe, expect, it } from 'vitest'
import { countCharacters, insertBlock, wrapInline } from './markdownInsert'

describe('insertBlock（ブロックは独立した段落にする）', () => {
  it('空の本文にはそのまま入る', () => {
    const result = insertBlock('', 0, 0, '## 要約')
    expect(result.text).toBe('## 要約\n')
    // キャレットは挿入した行の末尾
    expect(result.selectionStart).toBe('## 要約'.length)
  })

  it('直前の行に続けて入れると、空行を挟んで段落を分ける', () => {
    const before = '本文の途中'
    const result = insertBlock(before, before.length, before.length, '## 要約')
    expect(result.text).toBe('本文の途中\n\n## 要約\n')
  })

  it('直前が改行1つなら、もう1つだけ足す', () => {
    const result = insertBlock('本文\n', 3, 3, '- 項目')
    expect(result.text).toBe('本文\n\n- 項目\n')
  })

  it('直前がすでに空行なら改行を足さない', () => {
    const before = '本文\n\n'
    const result = insertBlock(before, before.length, before.length, '- 項目')
    expect(result.text).toBe('本文\n\n- 項目\n')
  })

  it('続きの本文がある途中に入れても、次の行と地続きにならない', () => {
    const text = '前の段落\n\n次の段落'
    const at = '前の段落\n\n'.length
    const result = insertBlock(text, at, at, '> 「引用」 p.96')
    expect(result.text).toBe('前の段落\n\n> 「引用」 p.96\n次の段落')
  })

  it('直後がすでに改行なら余分に足さない', () => {
    // 「前\n\n」の直後に入れる。後ろには改行がもう1つあるので足さない
    const text = '前\n\n\n後'
    const result = insertBlock(text, 3, 3, '- 項目')
    expect(result.text).toBe('前\n\n- 項目\n後')
  })

  it('選択範囲があればそれを置き換える', () => {
    const result = insertBlock('消える文字', 0, 5, '## 見出し')
    expect(result.text).toBe('## 見出し\n')
  })

  it('キャレットは挿入した行の末尾に来る', () => {
    const before = '本文'
    const result = insertBlock(before, 2, 2, '## 要約')
    // 「本文\n\n## 要約」までの長さ
    expect(result.text.slice(0, result.selectionStart)).toBe('本文\n\n## 要約')
    expect(result.selectionStart).toBe(result.selectionEnd)
  })
})

describe('wrapInline（インラインは選択範囲を囲む）', () => {
  it('選択した文字を記号で囲む', () => {
    const result = wrapInline('読みやすさが大事', 0, 5, '**', '**', '太字')
    expect(result.text).toBe('**読みやすさ**が大事')
  })

  it('囲んだ中身を選択したままにする', () => {
    const result = wrapInline('読みやすさが大事', 0, 5, '**', '**', '太字')
    expect(result.text.slice(result.selectionStart, result.selectionEnd)).toBe(
      '読みやすさ',
    )
  })

  it('選択が無ければ仮の文字を入れて囲む', () => {
    const result = wrapInline('', 0, 0, '**', '**', '太字')
    expect(result.text).toBe('**太字**')
  })

  it('入れた仮の文字を選んでおく（すぐ打ち替えられる）', () => {
    const result = wrapInline('', 0, 0, '**', '**', '太字')
    expect(result.text.slice(result.selectionStart, result.selectionEnd)).toBe('太字')
  })

  it('リンクのように開きと閉じが違ってもよい', () => {
    const result = wrapInline('参考', 0, 2, '[', '](https://)', 'リンク')
    expect(result.text).toBe('[参考](https://)')
  })

  it('本文の途中でも位置を崩さない', () => {
    const result = wrapInline('前と後', 1, 2, '~~', '~~', '取り消し')
    expect(result.text).toBe('前~~と~~後')
  })
})

describe('countCharacters（空白と記法の記号は数えない）', () => {
  it('記法の記号を除いて数える', () => {
    // 「要約」の2文字だけ
    expect(countCharacters('## 要約')).toBe(2)
  })

  it('空白と改行を数えない', () => {
    expect(countCharacters('あ い\nう')).toBe(3)
  })

  it('引用と箇条書きの記号も数えない', () => {
    expect(countCharacters('> 引用\n- 項目')).toBe(4)
  })

  it('太字の記号を数えない', () => {
    expect(countCharacters('**重要**')).toBe(2)
  })

  it('空の本文は0', () => {
    expect(countCharacters('')).toBe(0)
  })
})
