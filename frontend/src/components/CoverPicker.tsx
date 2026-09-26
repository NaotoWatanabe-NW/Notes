import { useRef, useState } from 'react'
import { ApiError, deleteCover, setCover } from '../api'
import { Cover } from './Cover'

type Props = {
  bookId: number
  title: string
  author: string | null
  coverUrl: string | null
  size?: 'md' | 'lg'
  /** 入れ替えたあと、画面のデータを取り直してもらう */
  onChanged: () => void
  onError: (message: string) => void
}

/**
 * 表紙を手で入れるための部品。
 * ISBN から自動で取れた本には出さなくてもよいが、取れなかった本や
 * 差し替えたい本のために、いつでも押せるようにしてある。
 */
export function CoverPicker({
  bookId,
  title,
  author,
  coverUrl,
  size = 'lg',
  onChanged,
  onError,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)

  async function pick(file: File | undefined) {
    if (!file) return
    setBusy(true)
    try {
      await setCover(bookId, file)
      onChanged()
    } catch (e) {
      onError(e instanceof ApiError ? e.message : '表紙を入れられませんでした')
    } finally {
      setBusy(false)
      // 同じファイルをもう一度選べるようにする
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function remove() {
    setBusy(true)
    try {
      await deleteCover(bookId)
      onChanged()
    } catch (e) {
      onError(e instanceof ApiError ? e.message : '表紙を外せませんでした')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cover-picker">
      <Cover title={title} author={author} src={coverUrl} size={size} />
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => pick(e.target.files?.[0])}
      />
      <button
        type="button"
        className="btn btn-ghost cover-picker-btn"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
      >
        <i className="ph-duotone ph-image" />
        {busy ? '…' : coverUrl ? '表紙を変える' : '表紙を選ぶ'}
      </button>
      {coverUrl ? (
        <button
          type="button"
          className="btn btn-ghost cover-picker-btn"
          disabled={busy}
          onClick={remove}
        >
          外す
        </button>
      ) : null}
    </div>
  )
}
