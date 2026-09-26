import { useRef, useState } from 'react'
import type { BookCreate, BookInfo, BookStatus } from '../api'
import { ApiError, lookupIsbn, searchCatalog, STATUS_LABELS } from '../api'
import { Cover } from './Cover'
import { Segmented } from './Segmented'
import { TagEditor } from './TagEditor'

type Props = {
  tagSuggestions: string[]
  /** 登録する。表紙のファイルを選んでいれば一緒に渡す */
  onCreate: (payload: BookCreate, cover: File | null) => Promise<void>
  onCancel: () => void
}

const EMPTY = {
  isbn: '',
  title: '',
  author: '',
  publisher: '',
  total: '',
  cover_url: null as string | null,
  category: null as string | null,
  status: 'unread' as BookStatus,
  tags: [] as string[],
}

/** 本を1冊追加する画面。ISBN・書名から引くか、手で打つ */
export function AddBookView({ tagSuggestions, onCreate, onCancel }: Props) {
  const [form, setForm] = useState(EMPTY)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<BookInfo[] | null>(null)
  const [busy, setBusy] = useState<'none' | 'isbn' | 'search' | 'save'>('none')
  // 自動で表紙が取れない本のために、手で選べるようにしてある
  const [cover, setCover] = useState<File | null>(null)
  const coverInput = useRef<HTMLInputElement>(null)
  const [message, setMessage] = useState<string | null>(null)

  /** 検索で見つかった情報をフォームに流し込む */
  function fill(info: BookInfo) {
    setForm((prev) => ({
      ...prev,
      isbn: info.isbn,
      title: info.title,
      author: info.author ?? '',
      publisher: info.publisher ?? '',
      total: info.total ? String(info.total) : '',
      cover_url: info.cover_url,
      category: info.category,
    }))
    setMessage(`${info.source} から取得しました`)
    setHits(null)
  }

  async function lookup() {
    if (!form.isbn.trim()) return
    setBusy('isbn')
    setMessage(null)
    try {
      fill(await lookupIsbn(form.isbn.trim()))
    } catch (e) {
      // 見つからなくても手入力で先に進めるようにする
      setMessage(e instanceof ApiError ? e.message : '取得できませんでした')
    } finally {
      setBusy('none')
    }
  }

  async function search() {
    if (query.trim().length < 2) return
    setBusy('search')
    setMessage(null)
    setHits(null)
    try {
      const found = await searchCatalog(query.trim(), 6)
      setHits(found)
      if (found.length === 0) setMessage(`「${query.trim()}」は見つかりませんでした`)
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : '検索できませんでした')
    } finally {
      setBusy('none')
    }
  }

  async function save() {
    if (!form.title.trim() || busy === 'save') return
    setBusy('save')
    try {
      await onCreate({
        title: form.title.trim(),
        isbn: form.isbn.trim() || null,
        author: form.author.trim() || null,
        publisher: form.publisher.trim() || null,
        category: form.category,
        cover_url: form.cover_url,
        total: form.total ? Number(form.total) : null,
        status: form.status,
        tags: form.tags,
      }, cover)
      setForm(EMPTY)
      setCover(null)
      setQuery('')
      setMessage(null)
    } catch {
      // 失敗の文言は App 側が画面に出す。入力は消さずに残す
    } finally {
      setBusy('none')
    }
  }

  return (
    <div className="detail">
      <header className="section-head">
        <h1 className="section-title">本を追加</h1>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          やめる
        </button>
      </header>

      <section className="add-form">
        {/* ── 書名で探す ── */}
        <label htmlFor="add-query">書名・著者で探す</label>
        <div className="add-row">
          <input
            id="add-query"
            className="input"
            value={query}
            placeholder="達人プログラマー"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void search()
              }
            }}
          />
          <button
            type="button"
            className="btn btn-secondary"
            disabled={query.trim().length < 2 || busy !== 'none'}
            onClick={search}
          >
            {busy === 'search' ? '探しています…' : '探す'}
          </button>
        </div>
        {busy === 'search' ? (
          /* 初めて引く言葉は国立国会図書館の応答が遅い（実測で最大40秒） */
          <p className="row-meta">
            初めて調べる言葉は30秒ほどかかることがあります。一度調べた言葉は次から早くなります。
          </p>
        ) : null}

        {hits && hits.length > 0 ? (
          <div className="hits">
            {hits.map((info) => (
              <button
                key={info.isbn}
                type="button"
                className="row"
                onClick={() => fill(info)}
              >
                <Cover title={info.title} author={info.author} src={info.cover_url} />
                <span className="row-main">
                  <span className="row-title">{info.title}</span>
                  <span className="row-meta">
                    {[info.author, info.publisher].filter(Boolean).join(' · ')}
                  </span>
                </span>
              </button>
            ))}
          </div>
        ) : null}

        {/* ── ISBN で引く ── */}
        <label htmlFor="add-isbn">ISBN から引く</label>
        <div className="add-row">
          <input
            id="add-isbn"
            className="input"
            value={form.isbn}
            placeholder="978-4-274-22629-8"
            onChange={(e) => setForm({ ...form, isbn: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void lookup()
              }
            }}
          />
          <button
            type="button"
            className="btn btn-secondary"
            disabled={!form.isbn.trim() || busy !== 'none'}
            onClick={lookup}
          >
            {busy === 'isbn' ? '取得中…' : '取得'}
          </button>
        </div>

        {message ? <p className="row-meta">{message}</p> : null}
      </section>

      {/* ── 取得した内容の確認と手直し ── */}
      <section className="add-form">
        {form.cover_url || form.title ? (
          <div className="found">
            <Cover
              title={form.title || '未入力'}
              author={form.author}
              src={cover ? URL.createObjectURL(cover) : form.cover_url}
            />
            <span className="stack" style={{ gap: 4 }}>
              <span className="row-meta">
                {form.cover_url || cover
                  ? '取得した内容はここで直せます。'
                  : 'この本の表紙は自動で取れませんでした。手で入れられます。'}
              </span>
              <span style={{ display: 'flex', gap: 4 }}>
                <input
                  ref={coverInput}
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(e) => setCover(e.target.files?.[0] ?? null)}
                />
                <button
                  type="button"
                  className="btn btn-ghost"
                  style={{ fontSize: 12 }}
                  onClick={() => coverInput.current?.click()}
                >
                  <i className="ph-duotone ph-image" />
                  {cover ? '表紙を変える' : '表紙を選ぶ'}
                </button>
                {cover ? (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    style={{ fontSize: 12 }}
                    onClick={() => setCover(null)}
                  >
                    外す
                  </button>
                ) : null}
              </span>
            </span>
          </div>
        ) : null}

        <label>
          タイトル
          <input
            className="input"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        </label>
        <label>
          著者
          <input
            className="input"
            value={form.author}
            onChange={(e) => setForm({ ...form, author: e.target.value })}
          />
        </label>
        <label>
          出版社
          <input
            className="input"
            value={form.publisher}
            onChange={(e) => setForm({ ...form, publisher: e.target.value })}
          />
        </label>
        <label>
          総ページ数
          <input
            className="input input-narrow"
            type="number"
            min={1}
            value={form.total}
            placeholder="422"
            onChange={(e) => setForm({ ...form, total: e.target.value })}
          />
        </label>

        <div className="stack" style={{ gap: 5 }}>
          <span style={{ fontSize: 12, color: 'var(--color-neutral-700)' }}>状態</span>
          <Segmented
            name="add-status"
            value={form.status}
            options={(Object.keys(STATUS_LABELS) as BookStatus[]).map((key) => ({
              value: key,
              label: STATUS_LABELS[key],
            }))}
            onChange={(status) => setForm({ ...form, status })}
          />
        </div>

        <div className="stack" style={{ gap: 5 }}>
          <span style={{ fontSize: 12, color: 'var(--color-neutral-700)' }}>タグ</span>
          <TagEditor
            tags={form.tags}
            suggestions={tagSuggestions}
            onChange={(tags) => setForm({ ...form, tags })}
          />
        </div>

        <button
          type="button"
          className="btn btn-primary"
          style={{ justifySelf: 'start' }}
          disabled={!form.title.trim() || busy === 'save'}
          onClick={save}
        >
          {busy === 'save' ? '登録中…' : '本棚に追加'}
        </button>
      </section>
    </div>
  )
}
