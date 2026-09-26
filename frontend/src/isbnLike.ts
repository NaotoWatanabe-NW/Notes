/**
 * 打たれた文字列が ISBN らしいかどうか。
 *
 * 検索欄に ISBN を打ったときに「この番号で追加」を出すための判定なので、
 * チェックディジットまでは見ない（厳密な検証はサーバー側がやる）。
 */
export function looksLikeIsbn(query: string): boolean {
  const cleaned = query.replace(/[\s-]/g, '')
  // ISBN-10（末尾が X のことがある）か ISBN-13
  return /^\d{9}[\dX]$/i.test(cleaned) || /^\d{13}$/.test(cleaned)
}
