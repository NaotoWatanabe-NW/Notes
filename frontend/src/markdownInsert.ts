/**
 * Markdown をカーソル位置に差し込むときの規則（デザイン #6a）。
 *
 * - ブロック（見出し・章・引用・リスト・メモ）は**必ず独立した段落**にする。
 *   前後の改行が足りなければ補う。キャレットは挿入した行の末尾へ。
 * - インライン（太字・斜体・取り消し・語句・リンク）は選択範囲を囲む。
 *   選択が無ければ仮の文字を入れて囲み、その仮の文字を選んでおく。
 *
 * textarea を直接いじると条件分岐が散らかるので、ここでは「次の本文と
 * 次の選択範囲」だけを計算して返す。
 */
export type InsertResult = {
  text: string
  selectionStart: number
  selectionEnd: number
}

/** 独立した段落としてブロックを差し込む */
export function insertBlock(
  text: string,
  start: number,
  end: number,
  block: string,
): InsertResult {
  const before = text.slice(0, start)
  const after = text.slice(end)

  // 直前が空でなければ、空行を1つ挟んで段落を分ける
  let lead = ''
  if (before !== '') {
    const trailing = /\n*$/.exec(before)?.[0].length ?? 0
    lead = '\n'.repeat(Math.max(0, 2 - trailing))
  }
  // 直後にも改行を足して、次の行と地続きにならないようにする
  const leading = /^\n*/.exec(after)?.[0].length ?? 0
  const tail = '\n'.repeat(Math.max(0, 1 - leading))

  const caret = before.length + lead.length + block.length
  return {
    text: before + lead + block + tail + after,
    selectionStart: caret,
    selectionEnd: caret,
  }
}

/** 選択範囲を記号で囲む。選択が無ければ仮の文字を入れて囲む */
export function wrapInline(
  text: string,
  start: number,
  end: number,
  open: string,
  close: string,
  placeholder: string,
): InsertResult {
  const selected = text.slice(start, end)
  const body = selected || placeholder
  const from = start + open.length
  return {
    text: text.slice(0, start) + open + body + close + text.slice(end),
    // 入れた中身を選んでおく。仮の文字ならそのまま打ち替えられる
    selectionStart: from,
    selectionEnd: from + body.length,
  }
}

/**
 * 文字数。空白と Markdown の記号は数えない（デザインの指定）。
 */
export function countCharacters(markdown: string): number {
  return markdown.replace(/[#>*\-\s]/g, '').length
}
