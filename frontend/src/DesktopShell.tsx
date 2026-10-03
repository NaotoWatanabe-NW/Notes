import { useEffect, useMemo, useState } from 'react'
import type { Review, ReviewPeriod } from './api'
import * as api from './api'
import type { AppData } from './useAppData'
import { AddBookView } from './components/AddBookView'
import { BookDetailView } from './components/BookDetailView'
import type { PaletteAction } from './components/CommandPalette'
import { CommandPalette } from './components/CommandPalette'
import { LibraryPane } from './components/LibraryPane'
import { NoteDetailView } from './components/NoteDetailView'
import { NextBookDialog } from './components/NextBookDialog'
import { NotesPane } from './components/NotesPane'
import { Rail } from './components/Rail'
import { ReportEditor } from './components/ReportEditor'
import { ReviewPane } from './components/ReviewPane'
import { ReviewView } from './components/ReviewView'
import type { SettingsSection } from './components/SettingsPane'
import { SettingsPane } from './components/SettingsPane'
import { SettingsView } from './components/SettingsView'
import { SuggestionsPane } from './components/SuggestionsPane'
import { SuggestionsView } from './components/SuggestionsView'
import { Toast } from './components/Toast'
import type { LibraryFilter, NoteFilter, View } from './types'
import { groupBySource, markShelved, matchesKeyword } from './suggestionSearch'
import { useAllSuggestions } from './useAllSuggestions'
import { filtersRevealing } from './visibility'

export function DesktopShell({ data }: { data: AppData }) {
  const {
    books,
    notes,
    tags,
    settings,
    toast,
    setToast,
    selectedBookId,
    setSelectedBookId,
    bookDetail,
    bookNotes,
    justFinished,
    clearJustFinished,
    reload,
    notify,
    fail,
    updateBook,
    addBook,
    addNote,
    changeNote,
    removeNote,
    removeBook,
    changeSettings,
  } = data

  const [view, setView] = useState<View>('library')
  const [periods, setPeriods] = useState<ReviewPeriod[]>([])

  const [libraryFilter, setLibraryFilter] = useState<LibraryFilter>(null)
  const [tagFilter, setTagFilter] = useState<string | null>(null)
  const [genreFilter, setGenreFilter] = useState<api.Genre | null>(null)
  // 本を追加する画面を出しているか
  const [adding, setAdding] = useState(false)
  const [noteFilter, setNoteFilter] = useState<NoteFilter>(null)
  const [selectedNoteId, setSelectedNoteId] = useState<number | null>(null)
  const [settingsSection, setSettingsSection] = useState<SettingsSection>('goal')
  const [period, setPeriod] = useState<string | null>(null)
  // おすすめ一覧のキーワードと、選んでいる本（null は「すべての本から」）
  const [suggestionQuery, setSuggestionQuery] = useState('')
  const [suggestionSourceId, setSuggestionSourceId] = useState<number | null>(null)

  const [review, setReview] = useState<Review | null>(null)
  const [yearReview, setYearReview] = useState<Review | null>(null)

  const [paletteOpen, setPaletteOpen] = useState(false)
  const [writingBookId, setWritingBookId] = useState<number | null>(null)
  // 一覧ペインを畳んでいるか。詳細を広く読みたいときに使う
  const [sidebarHidden, setSidebarHidden] = useState(false)
  // 読了ダイアログから積読に足したとき、詳細の「次に読む本」を取り直すための目印
  const [detailEpoch, setDetailEpoch] = useState(0)

  // 振り返りの期間
  useEffect(() => {
    if (view !== 'review') return
    api
      .listPeriods()
      .then((loaded) => {
        setPeriods(loaded)
        setPeriod((prev) => prev ?? loaded[0]?.period ?? null)
      })
      .catch(() => undefined)
  }, [view, books])

  useEffect(() => {
    if (period === null) return
    api.getReview(period).then(setReview).catch(() => undefined)
  }, [period, books, notes])

  // 設定画面の「今年はここまで◯冊」に使う
  useEffect(() => {
    if (view !== 'settings') return
    api
      .getReview(String(new Date().getFullYear()))
      .then(setYearReview)
      .catch(() => undefined)
  }, [view, books])

  // ⌘K の開閉と Esc、⌘B で一覧ペインの開閉
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((prev) => !prev)
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'b') {
        event.preventDefault()
        setSidebarHidden((prev) => !prev)
      } else if (event.key === 'Escape' && paletteOpen) {
        event.preventDefault()
        setPaletteOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [paletteOpen])

  // ---------------------------------------------------------------- 操作

  /**
   * その本を隠してしまう絞り込みだけを外す。
   *
   * 絞り込みが効いていると、追加した本が一覧に出てこない
   * （読了タブを見ているときに積読の本を足した、など）。
   * 関係のない絞り込みは触らないので、ユーザーが選んだ状態をむやみに壊さない。
   */
  function unhideBook(book: api.Book) {
    const next = filtersRevealing(book, {
      status: libraryFilter,
      tag: tagFilter,
      genre: genreFilter,
    })
    setLibraryFilter(next.status)
    setTagFilter(next.tag)
    setGenreFilter(next.genre)
  }

  /** 本棚でその本を開く。隠れていたら絞り込みを外してから選ぶ */
  function revealBook(book: api.Book) {
    unhideBook(book)
    setView('library')
    setAdding(false)
    setSelectedBookId(book.id)
  }

  /** id から本を探して開く。一覧に無ければ id だけで選ぶ */
  function openBookById(id: number) {
    const book = books.find((item) => item.id === id)
    if (book) {
      revealBook(book)
      return
    }
    setView('library')
    setAdding(false)
    setSelectedBookId(id)
  }

  async function runPaletteAction(action: PaletteAction) {
    setPaletteOpen(false)
    if (action.type === 'openBook') {
      openBookById(action.bookId)
      return
    }
    if (action.type === 'openNote') {
      const note = notes.find((item) => item.id === action.noteId)
      // その記録を隠してしまう絞り込みだけ外す
      if (note && noteFilter !== null && note.kind !== noteFilter) {
        setNoteFilter(null)
      }
      setView('notes')
      setSelectedNoteId(action.noteId)
      return
    }
    if (action.type === 'writeNote') {
      openBookById(action.bookId)
      return
    }

    // 外部カタログからの追加。常に「積読」から始まる（デザインの仕様）
    try {
      let info = action.info
      if (!info.title) info = await api.lookupIsbn(info.isbn)
      const created = await addBook({
        isbn: info.isbn,
        title: info.title,
        author: info.author,
        publisher: info.publisher,
        category: info.category,
        cover_url: info.cover_url,
        total: info.total,
        status: 'unread',
      })
      revealBook(created)
      notify(`「${created.title}」を積読に追加しました`)
    } catch (error) {
      fail(error, '本を追加できませんでした')
    }
  }

  // ---------------------------------------------------------------- 描画

  const selectedBook = useMemo(
    () => books.find((book) => book.id === selectedBookId) ?? null,
    [books, selectedBookId],
  )
  const selectedNote = useMemo(
    () => notes.find((note) => note.id === selectedNoteId) ?? null,
    [notes, selectedNoteId],
  )
  const writingBook =
    writingBookId !== null && bookDetail?.id === writingBookId ? bookDetail : null

  const allSuggestions = useAllSuggestions(view === 'suggestions', {
    onAdded: () => void reload(),
    onError: setToast,
  })
  const suggestionGroups = useMemo(
    () =>
      groupBySource(
        markShelved(allSuggestions.items, books).filter((item) =>
          matchesKeyword(item, suggestionQuery),
        ),
      ),
    [allSuggestions.items, books, suggestionQuery],
  )
  // 選んでいる本の候補がキーワードで全部消えたら、「すべての本から」を出す
  const selectedSuggestionGroup = suggestionGroups.find(
    (group) => group.book.id === suggestionSourceId,
  )
  const shownSuggestionGroups = selectedSuggestionGroup
    ? [selectedSuggestionGroup]
    : suggestionGroups

  function renderList() {
    if (view === 'library') {
      return (
        <LibraryPane
          books={books}
          filter={libraryFilter}
          tagFilter={tagFilter}
          genreFilter={genreFilter}
          selectedId={selectedBookId}
          onFilter={setLibraryFilter}
          onTagFilter={setTagFilter}
          onGenreFilter={setGenreFilter}
          onSelect={(id) => {
            setAdding(false)
            setSelectedBookId(id)
          }}
          onOpenPalette={() => setPaletteOpen(true)}
          onAdd={() => setAdding(true)}
        />
      )
    }
    if (view === 'notes') {
      return (
        <NotesPane
          notes={notes}
          filter={noteFilter}
          selectedId={selectedNoteId}
          onFilter={setNoteFilter}
          onSelect={setSelectedNoteId}
        />
      )
    }
    if (view === 'review') {
      return (
        <ReviewPane periods={periods} selected={period} onSelect={setPeriod} />
      )
    }
    if (view === 'suggestions') {
      return (
        <SuggestionsPane
          groups={suggestionGroups}
          total={suggestionGroups.reduce((sum, group) => sum + group.items.length, 0)}
          query={suggestionQuery}
          onQuery={setSuggestionQuery}
          selectedId={selectedSuggestionGroup?.book.id ?? null}
          onSelect={setSuggestionSourceId}
          loading={allSuggestions.loading}
        />
      )
    }
    return <SettingsPane selected={settingsSection} onSelect={setSettingsSection} />
  }

  function renderDetail() {
    if (view === 'library') {
      if (adding) {
        return (
          <AddBookView
            tagSuggestions={tags.map((tag) => tag.name)}
            onCreate={async (payload, cover) => {
              const created = await addBook(payload)
              // 表紙は本ができてからでないと付けられない
              if (cover) {
                try {
                  await api.setCover(created.id, cover)
                  await reload()
                } catch (error) {
                  fail(error, '表紙を入れられませんでした')
                }
              }
              revealBook(created)
              notify(`「${created.title}」を追加しました`)
            }}
            onCancel={() => setAdding(false)}
          />
        )
      }
      if (!bookDetail) {
        return (
          <p className="detail-empty">
            左から本を選ぶと、進捗・引用・メモがここに出ます。
          </p>
        )
      }
      return (
        <BookDetailView
          // ダイアログで積読に足したあと、詳細側の候補にも印を出すために組み直す
          key={`${bookDetail.id}-${detailEpoch}`}
          book={bookDetail}
          notes={bookNotes}
          tagSuggestions={tags.map((tag) => tag.name)}
          onUpdate={(payload) => updateBook(bookDetail.id, payload)}
          onAddNote={(payload) => addNote(bookDetail.id, payload)}
          onUpdateNote={changeNote}
          onDeleteNote={removeNote}
          onWriteReport={() => setWritingBookId(bookDetail.id)}
          onDelete={() => removeBook(bookDetail)}
          onReload={() => void reload()}
          onError={setToast}
          onNotify={setToast}
          onFilterTag={(tag) => {
            // タグを押したら、本棚をそのタグだけで絞り込む（デザイン 8b）
            setTagFilter(tag)
            setLibraryFilter(null)
            setGenreFilter(null)
          }}
        />
      )
    }
    if (view === 'notes') {
      if (!selectedNote) {
        return <p className="detail-empty">左から記録を選ぶと、全文が出ます。</p>
      }
      return (
        <NoteDetailView
          note={selectedNote}
          siblings={notes}
          onSelectNote={setSelectedNoteId}
          onOpenBook={openBookById}
        />
      )
    }
    if (view === 'review') {
      if (!review) return <p className="detail-empty">期間を選んでください。</p>
      return (
        <ReviewView
          review={review}
          sub={periods.find((p) => p.period === period)?.sub ?? ''}
          onOpenBook={openBookById}
        />
      )
    }
    if (view === 'suggestions') {
      return (
        <SuggestionsView
          groups={shownSuggestionGroups}
          query={suggestionQuery}
          loading={allSuggestions.loading}
          onOpenBook={openBookById}
          onAdd={(item) => void allSuggestions.add(item)}
          onDismiss={(item) => void allSuggestions.dismiss(item)}
        />
      )
    }
    if (!settings) return <p className="detail-empty">読み込み中…</p>
    return (
      <SettingsView
        section={settingsSection}
        settings={settings}
        yearReview={yearReview}
        books={books}
        notes={notes}
        onChange={changeSettings}
      />
    )
  }

  return (
    <div className="shell">
      <Rail
        view={view}
        onChange={setView}
        onOpenPalette={() => setPaletteOpen(true)}
        sidebarHidden={sidebarHidden}
        onToggleSidebar={() => setSidebarHidden((prev) => !prev)}
      />
      {/* レール以外（一覧＋詳細）をひとかたまりにして画面の中央に寄せる。
          隠すときは表示だけ消す（要素は残すので、絞り込みや位置は元のまま戻る） */}
      <div className={`panes${sidebarHidden ? ' panes-solo' : ''}`}>
        <aside className="list-pane">{renderList()}</aside>
        <main className="detail-pane">{renderDetail()}</main>
      </div>

      {writingBook ? (
        <ReportEditor
          book={writingBook}
          notes={bookNotes}
          escActive={!paletteOpen}
          onSave={(markdown) => {
            // 自動保存。閉じずに静かに書き込むだけ
            void updateBook(writingBook.id, { report_md: markdown })
          }}
          onClose={async (markdown) => {
            await updateBook(writingBook.id, { report_md: markdown })
            setWritingBookId(null)
            notify('レポートを保存しました')
          }}
          onUpdateBook={(payload) => updateBook(writingBook.id, payload)}
        />
      ) : null}

      {paletteOpen ? (
        <CommandPalette
          books={books}
          notes={notes}
          selectedBook={selectedBook}
          onRun={runPaletteAction}
          onClose={() => setPaletteOpen(false)}
        />
      ) : null}

      {justFinished !== null ? (
        <NextBookDialog
          bookId={justFinished}
          rating={books.find((book) => book.id === justFinished)?.rating ?? null}
          onRate={(rating) => updateBook(justFinished, { rating })}
          onAdded={() => {
            // 追加はサーバー側で済んでいる。一覧を取り直し、
            // ダイアログを閉じたときに見つかるよう絞り込みも外しておく
            void reload()
            setLibraryFilter(null)
            setTagFilter(null)
            setGenreFilter(null)
            setDetailEpoch((prev) => prev + 1)
          }}
          onWriteReport={() => {
            setWritingBookId(justFinished)
            clearJustFinished()
          }}
          onClose={clearJustFinished}
          onError={(message) => setToast(message)}
        />
      ) : null}

      {toast ? <Toast message={toast} onDone={() => setToast(null)} /> : null}
    </div>
  )
}
