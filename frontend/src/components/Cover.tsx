import { useState } from 'react'

type Props = {
  title: string
  author?: string | null
  src?: string | null
  /** sm 36×52 / md 72×104 / lg 120×176。row・tile・sheet はモバイルのおすすめ（7h・7a・7i） */
  size?: 'sm' | 'md' | 'lg' | 'row' | 'tile' | 'sheet'
}

/**
 * 表紙。画像が無い本や、読み込みに失敗した本には同じ形のプレースホルダーを出す。
 * 壊れた画像アイコンが並ぶと一覧が散らかるため。
 */
export function Cover({ title, author, src, size = 'sm' }: Props) {
  const [failed, setFailed] = useState(false)
  const sizeClass = `cover cover-${size}`

  if (src && !failed) {
    return (
      <img
        src={src}
        alt=""
        // 画面に入るまで読まない。おすすめ一覧のように数百冊並ぶと、
        // 書影の中継（国会図書館）にまとめて問い合わせてしまうため
        loading="lazy"
        onError={() => setFailed(true)}
        className={sizeClass}
      />
    )
  }
  return (
    <div className={`${sizeClass} cover-ph`} aria-hidden="true">
      <span className="cover-ph-title">{title}</span>
      {author ? <span className="cover-ph-author">{author}</span> : null}
    </div>
  )
}
